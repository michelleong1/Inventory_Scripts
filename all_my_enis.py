#!/usr/bin/env python3

# import boto3
import Inventory_Modules
from Inventory_Modules import get_credentials_for_accounts_in_org, display_results, get_all_credentials
from ArgumentsClass import CommonArguments
from account_class import aws_acct_access
from colorama import init, Fore
from botocore.exceptions import ClientError
from queue import Queue
from threading import Thread
from time import time

import logging

init()

__version__ = '2023-04-14'

parser = CommonArguments()
parser.multiprofile()
parser.multiregion()
parser.extendedargs()
parser.rootOnly()
parser.timing()
parser.verbosity()
parser.version(__version__)
parser.my_parser.add_argument(
	"--ipaddress", "--ip",
	dest="pipaddresses",
	nargs="*",
	metavar="IP address",
	default=None,
	help="IP address(es) you're looking for within your accounts")
args = parser.my_parser.parse_args()

pProfiles = args.Profiles
pRegionList = args.Regions
pSkipAccounts = args.SkipAccounts
pSkipProfiles = args.SkipProfiles
pAccounts = args.Accounts
pRootOnly = args.RootOnly
pIPaddressList = args.pipaddresses
pTiming = args.Time
verbose = args.loglevel
logging.basicConfig(level=args.loglevel, format="[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s")

##################

ERASE_LINE = '\x1b[2K'

logging.info(f"Profiles: {pProfiles}")


##################


def check_accounts_for_subnets(fCredentialList, fip=None):
	"""
	Note that this function takes a list of Credentials and checks for ENIs in every account and region it has creds for
	"""

	class FindENIs(Thread):

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
					account_enis = Inventory_Modules.find_account_enis2(c_account_credentials, c_region, c_fip)
					logging.info(f"Successfully connected to account {c_account_credentials['AccountId']} in region {c_region}")
					for k, v in account_enis.items():
						v['MgmtAccount'] = c_account_credentials['MgmtAccount']
					Results.append(account_enis)
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

	checkqueue = Queue()

	Results = []
	PlaceCount = 0
	PlacesToLook = WorkerThreads = min(len(fCredentialList), 50)

	for x in range(WorkerThreads):
		worker = FindENIs(checkqueue)
		# Setting daemon to True will let the main thread exit even though the workers are blocking
		worker.daemon = True
		worker.start()

	for credential in fCredentialList:
		logging.info(f"Connecting to account {credential['AccountId']} in region {credential['Region']}")
		try:
			# print(f"{ERASE_LINE}Queuing account {credential['AccountId']} in region {region}", end='\r')
			checkqueue.put((credential, credential['Region'], fip, PlacesToLook, PlaceCount))
			PlaceCount += 1
		except ClientError as my_Error:
			if str(my_Error).find("AuthFailure") > 0:
				logging.error(f"Authorization Failure accessing account {credential['AccountId']} in {credential['Region']} region")
				logging.warning(f"It's possible that the region {credential['Region']} hasn't been opted-into")
				pass
	checkqueue.join()
	return (Results)


def display_enis(subnets_list):
	"""
	Note that this function simply formats the output of the data within the list provided
	"""
	for subnet in subnets_list:
		# print(subnet)
		print(f"{subnet['MgmtAccount']:12s} {subnet['AccountId']:12s} {subnet['Region']:15s} {subnet['SubnetName']:40s} {subnet['CidrBlock']:18s} {subnet['AvailableIpAddressCount']:5d}")


# AllSubnets.extend(subnets['Subnets'])
# AccountNum += 1


##################

begin_time = time()
print()
print(f"Checking for Subnets... ")
print()

ENIsFound = []
AllChildAccounts = []
RegionList = ['us-east-1']
subnet_list = []
AllCredentials = []

CredentialList = get_all_credentials(pProfiles, pTiming, pSkipProfiles, pSkipAccounts, pRootOnly, pAccounts, pRegionList)

display_dict = {'MgmtAccount': {'Format': '12s', 'DisplayOrder': 1, 'Heading': 'Mgmt Acct'},
                'AccountId'  : {'Format': '12s', 'DisplayOrder': 2, 'Heading': 'Acct Number'},
                'Region'     : {'Format': '15s', 'DisplayOrder': 3, 'Heading': 'Region'},
                'ENIName'    : {'Format': '40s', 'DisplayOrder': 4, 'Heading': 'ENI Name'},
                'IPAddress'  : {'Format': '18s', 'DisplayOrder': 5, 'Heading': 'Public IP Address'},
                'ENIType'    : {'Format': '8s',  'DisplayOrder': 6, 'Heading': 'ENIType'},
                'PrivateIP'  : {'Format': '15s', 'DisplayOrder': 7, 'Heading': 'Assoc. IP'}}

ENIsFound.extend(check_accounts_for_subnets(CredentialList, fip=pIPaddressList))

display_results(ENIsFound, display_dict)

if pTiming:
	print(ERASE_LINE)
	print(f"{Fore.GREEN}This script took {time() - begin_time} seconds{Fore.RESET}")
print()
print(f"These accounts were skipped - as requested: {pSkipAccounts}")
print()
print(f"Found {len(ENIsFound)} ENIs across {len(AllCredentials)} accounts across {len(RegionList)} regions")
print()
print("Thank you for using this script")
print()