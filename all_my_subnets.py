#!/usr/bin/env python3

# import boto3
import Inventory_Modules
from ArgumentsClass import CommonArguments
from account_class import aws_acct_access
from colorama import init, Fore
from botocore.exceptions import ClientError
from queue import Queue
from threading import Thread
from time import time

import logging

init()

parser = CommonArguments()
parser.multiprofile()
parser.multiregion()
parser.extendedargs()
parser.rootOnly()
parser.verbosity()
parser.my_parser.add_argument(
	"--ipaddress", "--ip",
	dest="pipaddresses",
	nargs="*",
	metavar="IP address",
	default=None,
	help="IP address(es) you're looking for within your VPCs")
args = parser.my_parser.parse_args()

pProfiles = args.Profiles
pRegionList = args.Regions
pSkipAccounts = args.SkipAccounts
pRootOnly = args.RootOnly
pIPaddressList = args.pipaddresses
pTiming = args.Time
verbose = args.loglevel
logging.basicConfig(level=args.loglevel, format="[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s")

##################

ERASE_LINE = '\x1b[2K'

logging.info(f"Profiles: {pProfiles}")
WorkerThreads = 20


##################


def find_places_to_check(faws_acct):
	"""
	Note that this function checks the account AND any children accounts in the Org.
	"""

	class AssembleCredentials(Thread):

		def __init__(self, queue):
			Thread.__init__(self)
			self.queue = queue

		def run(self):
			while True:
				# Get the work from the queue and expand the tuple
				account_info = self.queue.get()
				logging.info(f"De-queued info for account {account_info['AccountId']}")
				try:
					logging.info(f"Attempting to connect to {account_info['AccountId']}")
					faccount_credentials = Inventory_Modules.get_child_access3(faws_acct, account_info['AccountId'])
					if faccount_credentials['Success']:
						logging.info(f"Successfully connected to account {account_info['AccountId']}")
					else:
						logging.error(f"Error connecting to account {account_info['AccountId']}.\n"
									  f"Error Message: {faccount_credentials['ErrorMessage']}")
					AllCreds.append(faccount_credentials)
				except ClientError as my_Error:
					if str(my_Error).find("AuthFailure") > 0:
						logging.error(f"{account['AccountId']}: Authorization failure using role: {account_credentials['Role']}")
						logging.warning(my_Error)
					elif str(my_Error).find("AccessDenied") > 0:
						logging.error(f"{account['AccountId']}: Access Denied failure using role: {account_credentials['Role']}")
						logging.warning(my_Error)
					else:
						logging.error(f"{account['AccountId']}: Other kind of failure using role: {account_credentials['Role']}")
						logging.warning(my_Error)
					continue
				except KeyError as my_Error:
					logging.error(f"Account Access failed - trying to access {account['AccountId']}")
					logging.info(f"Actual Error: {my_Error}")
					pass
				except AttributeError as my_Error:
					logging.error(f"Error: Likely that one of the supplied profiles {pProfiles} was wrong")
					logging.warning(my_Error)
					continue
				finally:
					self.queue.task_done()

	ChildAccounts = faws_acct.ChildAccounts
	if pTiming:
		print(f"{Fore.GREEN}Running 'find_places_to_check' for {faws_acct.acct_number} after {time() - begin_time} seconds, with {len(aws_acct.ChildAccounts)} child accounts{Fore.RESET}")
	account_credentials = {'Role': 'Nothing'}
	AccountNum = 0
	AllCreds = []
	credqueue = Queue()

	# Create x worker threads
	for x in range(WorkerThreads):
		worker = AssembleCredentials(credqueue)
		# Setting daemon to True will let the main thread exit even though the workers are blocking
		worker.daemon = True
		worker.start()

	for account in ChildAccounts:
		SkipAccounts = pSkipAccounts
		if account['AccountId'] in SkipAccounts:
			continue
		elif pRootOnly and not account['AccountId'] == account['MgmtAccount']:
			continue
		AccountNum += 1
		print(f"{ERASE_LINE}Queuing account info for {AccountNum} / {len(ChildAccounts)} accounts", end='\r')
		logging.info(f"Queuing account {account['AccountId']}")
		credqueue.put(account)
	# logging.info(f"Connected to account {account['AccountId']} using role {account_credentials['Role']}")
	# AllCreds.append(account_credentials)
	credqueue.join()
	return (AllCreds)


def check_accounts_for_subnets(CredentialList, fRegionList=None, fip=None):
	"""
	Note that this function checks the account AND any children accounts in the Org.
	"""

	class FindSubnets(Thread):

		def __init__(self, queue):
			Thread.__init__(self)
			self.queue = queue

		def run(self):
			while True:
				# Get the work from the queue and expand the tuple
				c_account_credentials, c_region, c_fip, c_PlacesToLook, c_PlaceCount = self.queue.get()
				logging.info(f"De-queued info for account {c_account_credentials['AccountId']}")
				try:
					logging.info(f"Attempting to connect to {c_account_credentials['AccountId']}")
					account_subnets = Inventory_Modules.find_account_subnets2(c_account_credentials, c_region, c_fip)
					logging.info(f"Successfully connected to account {c_account_credentials['AccountId']}")
					for y in range(len(account_subnets['Subnets'])):
						account_subnets['Subnets'][y]['MgmtAccount'] = c_account_credentials['MgmtAccount']
						account_subnets['Subnets'][y]['AccountId'] = c_account_credentials['AccountId']
						account_subnets['Subnets'][y]['Region'] = c_region
						account_subnets['Subnets'][y]['SubnetName'] = "None"
						if 'Tags' in account_subnets['Subnets'][y].keys():
							for tag in account_subnets['Subnets'][y]['Tags']:
								if tag['Key'] == 'Name':
									account_subnets['Subnets'][y]['SubnetName'] = tag['Value']
						account_subnets['Subnets'][y]['VPCId'] = account_subnets['Subnets'][y]['VpcId'] if 'VpcId' in account_subnets['Subnets'][y].keys() else None
					if len(account_subnets['Subnets']) > 0:
						AllSubnets.extend(account_subnets['Subnets'])
				except KeyError as my_Error:
					logging.error(f"Account Access failed - trying to access {c_account_credentials['AccountId']}")
					logging.info(f"Actual Error: {my_Error}")
					pass
				except AttributeError as my_Error:
					logging.error(f"Error: Likely that one of the supplied profiles {pProfiles} was wrong")
					logging.warning(my_Error)
					continue
				finally:
					print(f"{ERASE_LINE}Finished finding subnets in account {c_account_credentials['AccountId']} in region {c_region} - {c_PlaceCount} / {c_PlacesToLook}", end='\r')
					self.queue.task_done()

	AllSubnets = []
	PlaceCount = 0
	PlacesToLook = len(CredentialList) * len(fRegionList)

	if fRegionList is None:
		fRegionList = ['us-east-1']
	checkqueue = Queue()

	for x in range(WorkerThreads):
		worker = FindSubnets(checkqueue)
		# Setting daemon to True will let the main thread exit even though the workers are blocking
		worker.daemon = True
		worker.start()

	for credential in CredentialList:
		logging.info(f"Connecting to account {credential['AccountId']}")
		for region in fRegionList:
			try:
				# print(f"{ERASE_LINE}Queuing account {credential['AccountId']} in region {region}", end='\r')
				checkqueue.put((credential, region, fip, PlacesToLook, PlaceCount))
				PlaceCount += 1
			except ClientError as my_Error:
				if str(my_Error).find("AuthFailure") > 0:
					logging.error(f"Authorization Failure accessing account {credential['AccountId']} in {region} region")
					logging.warning(f"It's possible that the region {region} hasn't been opted-into")
					pass
	checkqueue.join()
	return (AllSubnets)


def display_subnets(subnets_list):
	"""

	"""
	for subnet in subnets_list:
		# print(subnet)
		print(f"{subnet['MgmtAccount']:12s} {subnet['AccountId']:12s} {subnet['Region']:15s} {subnet['SubnetName']:40s} {subnet['CidrBlock']:18s} {subnet['AvailableIpAddressCount']:5d}")
	# AllSubnets.extend(subnets['Subnets'])
	# AccountNum += 1


##################


"""
queue = Queue()
# Create 8 worker threads
for x in range(8):
	worker = DownloadWorker(queue)
	# Setting daemon to True will let the main thread exit even though the workers are blocking
	worker.daemon = True
	worker.start()
# Put the tasks into the queue as a tuple
for link in links:
	logger.info('Queueing {}'.format(link))
	queue.put((download_dir, link))
# Causes the main thread to wait for the queue to finish processing all the tasks
queue.join()
logging.info('Took %s', time() - ts)
"""
##################

begin_time = time()
print()
print(f"Checking for Subnets... ")
print()
print()
fmt = '%-12s %-12s %-15s %-40s %-18s %-5s'
print(fmt % ("Root Acct #", "Account #", "Region", "Subnet Name", "CIDR", "Available IPs"))
print(fmt % ("-----------", "---------", "------", "-----------", "----", "-------------"))

SubnetsFound = []
AllChildAccounts = []
RegionList = ['us-east-1']
subnet_list = []
AllCredentials = []

if pProfiles is None:  # Default use case from the classes
	logging.info("Using whatever the default profile is")
	aws_acct = aws_acct_access()
	RegionList = Inventory_Modules.get_regions3(aws_acct, pRegionList)
	if pTiming:
		print(f"{Fore.GREEN}Overhead consumed {time() - begin_time} seconds up till now{Fore.RESET}")
	logging.warning(f"Default profile will be used")
	# This should populate the list "AllCreds" with the credentials for the relevant accounts.
	logging.info(f"Queueing default profile for credentials")
	AllCredentials.extend(find_places_to_check(aws_acct))

else:
	ProfileList = Inventory_Modules.get_profiles(fprofiles=pProfiles)
	print(f"Capturing info for supplied profiles")
	logging.warning(f"These profiles are being checked {ProfileList}.")
	for profile in ProfileList:
		aws_acct = aws_acct_access(profile)
		RegionList = Inventory_Modules.get_regions3(aws_acct, pRegionList)
		if pTiming:
			print(f"{Fore.GREEN}Overhead consumed {time() - begin_time} seconds up till now{Fore.RESET}")
		logging.warning(f"Looking at {profile} account now... ")
		logging.info(f"Queueing {profile} for credentials")
		# This should populate the list "AllCreds" with the credentials for the relevant accounts.
		AllCredentials.extend(find_places_to_check(aws_acct))

SubnetsFound.extend(check_accounts_for_subnets(AllCredentials, RegionList, fip=pIPaddressList))
display_subnets(SubnetsFound)

end_time = time()
duration = end_time - begin_time
print(ERASE_LINE)
if pTiming:
	print(f"{Fore.GREEN}This script took {duration} seconds{Fore.RESET}")
print()
print(f"These accounts were skipped - as requested: {pSkipAccounts}")
print()
print(f"Found {len(SubnetsFound)} subnets across {len(AllCredentials)} accounts across {len(RegionList)} regions")
print()
print("Thank you for using this script")
print()