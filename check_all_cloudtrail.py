#!/usr/bin/env python3

# import boto3
import Inventory_Modules
from ArgumentsClass import CommonArguments
from account_class import aws_acct_access
from colorama import init, Fore
from botocore.exceptions import ClientError
# from prettytable import PrettyTable

import logging

init()

parser = CommonArguments()
parser.multiprofile()
parser.multiregion()
parser.verbosity()
args = parser.my_parser.parse_args()

pProfiles = args.Profiles
pRegionList = args.Regions
verbose = args.loglevel
logging.basicConfig(level=args.loglevel, format="[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s")

##################


ERASE_LINE = '\x1b[2K'

logging.info(f"Profiles: {pProfiles}")


##################
def check_accounts_for_cloudtrail(faws_acct, fRegionList=None):
	"""
	Note that this function checks the account AND any children accounts in the Org.
	"""
	ChildAccounts = faws_acct.ChildAccounts
	AllTrails = []
	account_credentials = {'Role': 'Nothing'}
	Trails = dict()
	if fRegionList is None:
		fRegionList = ['us-east-1']
	for account in ChildAccounts:
		logging.info(f"Connecting to account {account['AccountId']}")
		try:
			account_credentials = Inventory_Modules.get_child_access3(faws_acct, account['AccountId'])
			logging.info(f"Connected to account {account['AccountId']} using role {account_credentials['Role']}")
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
		except AttributeError as my_Error:
			logging.error(f"Error: Likely that one of the supplied profiles {pProfiles} was wrong")
			logging.warning(my_Error)
			continue
		for region in fRegionList:
			try:
				print(f"{ERASE_LINE}Checking account {account['AccountId']} in region {region}", end='\r')
				Trails = Inventory_Modules.find_account_cloudtrail2(account_credentials, region)
				logging.info(f"Root Account: {faws_acct.acct_number} Account: {account['AccountId']} Region: {region} | Found {len(Trails['trailList'])} trails")
			except ClientError as my_Error:
				if str(my_Error).find("AuthFailure") > 0:
					logging.error(f"Authorization Failure accessing account {account['AccountId']} in {region} region")
					logging.warning(f"It's possible that the region {region} hasn't been opted-into")
					pass
			if 'trailList' in Trails.keys():
				for y in range(len(Trails['trailList'])):
					Trails['trailList'][y]['MgmtAccount'] = account['MgmtAccount']
					Trails['trailList'][y]['AccountId'] = account['AccountId']
					Trails['trailList'][y]['Region'] = region
					TrailName = Trails['trailList'][y]['Name']
					MultiRegion = Trails['trailList'][y]['IsMultiRegionTrail']
					OrgTrail = Trails['trailList'][y]['IsOrganizationTrail']
					Bucket = Trails['trailList'][y]['S3BucketName']
					KMS = Trails['trailList'][y]['KmsKeyId'] if 'KmsKeyId' in Trails.keys() else None
					Trails['trailList'][y]['KMS'] = KMS
					CloudWatchLogArn = Trails['trailList'][y]['CloudWatchLogsLogGroupArn'] if 'CloudWatchLogsLogGroupArn' in Trails.keys() else None
					Trails['trailList'][y]['CloudWatchLogArn'] = CloudWatchLogArn
					HomeRegion = Trails['trailList'][y]['HomeRegion'] if 'HomeRegion' in Trails.keys() else None
					Trails['trailList'][y]['HomeRegion'] = HomeRegion
					SNSTopicName = Trails['trailList'][y]['SNSTopicName'] if 'SNSTopicName' in Trails.keys() else None
					Trails['trailList'][y]['SNSTopicName'] = SNSTopicName
					# fmt = '%-12s %-12s %-10s %-15s %-20s %-20s %-12s'
					# print(fmt % (faws_acct.acct_number, account['AccountId'], region, InstanceType, Name, Engine, State))
					print(f"{faws_acct.acct_number:12s} {account['AccountId']:12s} {region:15s} {TrailName:40s} {str(OrgTrail):15s} {Bucket:45s} ")
			AllTrails.extend(Trails['trailList'])
	return (AllTrails)


##################


print()
print(f"Checking for CloudTrails... ")
print()

print()
fmt = '%-12s %-12s %-15s %-40s %-15s %-45s'
print(fmt % ("Root Acct #", "Account #", "Region", "Trail Name", "Org Trail", "Bucket Name"))
print(fmt % ("-----------", "---------", "------", "----------", "---------", "-----------"))

TrailsFound = []
AllChildAccounts = []
RegionList = ['us-east-1']

if pProfiles is None:  # Default use case from the classes
	logging.info("Using whatever the default profile is")
	aws_acct = aws_acct_access()
	RegionList = Inventory_Modules.get_regions3(aws_acct, pRegionList)
	logging.warning(f"Default profile will be used")
	TrailsFound.extend(check_accounts_for_cloudtrail(aws_acct, RegionList))
	AllChildAccounts.extend(aws_acct.ChildAccounts)
else:
	ProfileList = Inventory_Modules.get_profiles(fprofiles=pProfiles, fSkipProfiles="skipplus")
	logging.warning(f"These profiles are being checked {ProfileList}.")
	for profile in ProfileList:
		aws_acct = aws_acct_access(profile)
		logging.warning(f"Looking at {profile} account now... ")
		RegionList = Inventory_Modules.get_regions3(aws_acct, pRegionList)
		TrailsFound.extend(check_accounts_for_cloudtrail(aws_acct, RegionList))
		AllChildAccounts.extend(aws_acct.ChildAccounts)

ChildAccountList = [[item['MgmtAccount'], item['AccountId']] for item in AllChildAccounts]
ChildAccountsWithCloudTrail = set([[item['MgmtAccount'], item['AccountId']] for item in TrailsFound])
ProblemAccounts = [item['AccountId'] for item in ChildAccountList if item not in ChildAccountsWithCloudTrail]

print(ERASE_LINE)
# if verbose < 50:
# 	print(f"This table represents the summary of CloudTrail within the Org:")
# 	x = PrettyTable()
# 	x.field_names = ['Root Account', 'Account', 'Region', 'CloudTrail Name', 'Org Trail', 'Bucket Name']
#
# 	for item in ChildAccountList:
# 		MgmtAccount = item[0]
# 		ChildAccount = item[1]
# 		for region in RegionList:
# 			trailFound = False
# 			for trail in TrailsFound:
# 				if trail['AccountId'] == ChildAccount and trail['Region'] == region:
# 					x.add_row([trail['MgmtAccount'], trail['AccountId'], region, trail['Name'], trail['IsOrganizationTrail'], trail['S3BucketName']])
# 					trailFound = True
# 				elif trailFound:
# 					pass
# 				else:
# 					x.add_row([MgmtAccount, ChildAccount, region, 'None', 'None', 'None'])
# 	print()
# 	print(x)
print()
print(f"Found {len(TrailsFound)} trails across {len(AllChildAccounts)} accounts across {len(RegionList)} regions")
print()
print("Thank you for using this script")
print()