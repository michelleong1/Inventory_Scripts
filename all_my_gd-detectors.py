#!/usr/bin/env python3

import sys
import pprint
import Inventory_Modules
import boto3
import argparse
from colorama import init, Fore
from botocore.exceptions import ClientError


import logging

init()

# UsageMsg="You can provide a level to determine whether this script considers only the 'credentials' file, the 'config' file, or both."
parser = argparse.ArgumentParser(
	description="We\'re going to find all resources within any of the profiles we have access to.",
	prefix_chars='-+/')
parser.add_argument(
	"-p", "--profile",
	dest="pProfile",
	metavar="profile to use",
	help="You need to specify a profile that represents the ROOT account.")
parser.add_argument(
	"-k", "--skip",
	dest="pSkipAccounts",
	nargs="*",
	metavar="Accounts to leave alone",
	default=[],
	help="These are the account numbers you don't want to screw with. Likely the core accounts.")
parser.add_argument(
	"+delete", "+forreal",
	dest="flagDelete",
	default=False,
	action="store_const",
	const=True,
	help="Whether to delete the detectors it finds.")
parser.add_argument(
	'+f', '--force',
	help="force deletion without asking first",
	action="store_const",
	dest="ForceDelete",
	const=True,
	default=False)
parser.add_argument(
	'-v',
	help="Be verbose",
	action="store_const",
	dest="loglevel",
	const=logging.ERROR,  # args.loglevel = 40
	default=logging.CRITICAL)  # args.loglevel = 50
parser.add_argument(
	'-vv', '--verbose',
	help="Be MORE verbose",
	action="store_const",
	dest="loglevel",
	const=logging.WARNING,  # args.loglevel = 30
	default=logging.CRITICAL)  # args.loglevel = 50
parser.add_argument(
	'-vvv',
	help="Print INFO level statements",
	action="store_const",
	dest="loglevel",
	const=logging.INFO,  # args.loglevel = 20
	default=logging.CRITICAL)  # args.loglevel = 50
parser.add_argument(
	'-d', '--debug',
	help="Print LOTS of debugging statements",
	action="store_const",
	dest="loglevel",
	const=logging.DEBUG,  # args.loglevel = 10
	default=logging.CRITICAL)  # args.loglevel = 50
args = parser.parse_args()

pProfile = args.pProfile
DeletionRun = args.flagDelete
ForceDelete = args.ForceDelete
AccountsToSkip = args.pSkipAccounts
logging.basicConfig(level=args.loglevel, format="[%(filename)s:%(lineno)s:%(levelname)s - %(funcName)20s() ] %(message)s")

##########################
ERASE_LINE = '\x1b[2K'

NumObjectsFound = 0
NumAccountsInvestigated = 0
ChildAccounts = Inventory_Modules.find_child_accounts2(pProfile)
ChildAccounts = Inventory_Modules.RemoveCoreAccounts(ChildAccounts, AccountsToSkip)

session_gd = boto3.Session(profile_name=pProfile)
gd_regions = session_gd.get_available_regions(service_name='guardduty')
# gd_regions=['us-east-1','us-west-2']
all_gd_detectors = []
all_gd_invites = []
print("Searching {} accounts and {} regions".format(len(ChildAccounts), len(gd_regions)))

sts_session = boto3.Session(profile_name=pProfile)
sts_client = sts_session.client('sts')
for account in ChildAccounts:
	logging.info(f"Checking Account: {account}")
	NumProfilesInvestigated = 0  # I only care about the last run - so I don't get profiles * regions.
	role_arn = f"arn:aws:iam::{account['AccountId']}:role/AWSCloudFormationStackSetExecutionRole"
	logging.info(f"Role ARN: {role_arn}")
	try:
		account_credentials = sts_client.assume_role(
			RoleArn=role_arn,
			RoleSessionName="Find-GuardDuty-Detectors")['Credentials']
	except ClientError as my_Error:
		if str(my_Error).find("AuthFailure") > 0:
			print(f"Authorization Failure for account {account['AccountId']}")
		sys.exit("Credentials failure")
	for region in gd_regions:
		logging.info(f"Checking Region: {region}")
		NumAccountsInvestigated += 1
		session_aws = boto3.Session(
			aws_access_key_id=account_credentials['AccessKeyId'],
			aws_secret_access_key=account_credentials['SecretAccessKey'],
			aws_session_token=account_credentials['SessionToken'],
			region_name=region)
		client_aws = session_aws.client('guardduty')
		logging.info(f"Token Info {account_credentials}")
		# List Invitations
		try:
			logging.info(f"About to List invites for account: {account} in region {region}")
			response = client_aws.list_invitations()
			logging.info(f"Finished listing invites for account: {account} in region {region}")
		except ClientError as my_Error:
			if str(my_Error).find("AuthFailure") > 0:
				print(f"{account['AccountId']}: Authorization Failure for account {account['AccountId']}")
			if str(my_Error).find("security token included in the request is invalid") > 0:
				print(f"Account #:{account['AccountId']} - It's likely that the region you're trying ({region}) isn't enabled for your account")
				continue
			else:
				print(my_Error)
				continue
		# if len(response['Invitations']) > 0:
		if 'Invitations' in response.keys():
			for i in range(len(response['Invitations'])):
				all_gd_invites.append({
					'AccountId': response['Invitations'][i]['AccountId'],
					'InvitationId': response['Invitations'][i]['InvitationId'],
					'Region': region,
					'AccessKeyId': account_credentials['AccessKeyId'],
					'SecretAccessKey': account_credentials['SecretAccessKey'],
					'SessionToken': account_credentials['SessionToken']
				})
		try:
			print(ERASE_LINE, f"Trying account {account['AccountId']} in region {region}", end='\r')
			response = client_aws.list_detectors()
			if len(response['DetectorIds']) > 0:
				NumObjectsFound = NumObjectsFound + len(response['DetectorIds'])
				all_gd_detectors.append({
					'AccountId': account['AccountId'],
					'Region': region,
					'DetectorIds': response['DetectorIds'],
					'AccessKeyId': account_credentials['AccessKeyId'],
					'SecretAccessKey': account_credentials['SecretAccessKey'],
					'SessionToken': account_credentials['SessionToken']
				})
				print("Found another detector {} in account {} in region {} bringing the total found to {} ".format(str(response['DetectorIds'][0]), account['AccountId'], region, str(NumObjectsFound)))
				# logging.info("Found another detector ("+str(response['DetectorIds'][0])+") in account "+account['AccountId']+" in region "+account['AccountId']+" bringing the total found to "+str(NumObjectsFound))
			else:
				print(ERASE_LINE, f"{Fore.RED}No luck in account: {account['AccountId']}{Fore.RESET}", end='\r')
		except ClientError as my_Error:
			if str(my_Error).find("AuthFailure") > 0:
				print(f"Authorization Failure for account {account['AccountId']}")

if args.loglevel < 50:
	print()
	fmt = '%-20s %-15s %-20s'
	print(fmt % ("Account ID", "Region", "Detector ID"))
	print(fmt % ("----------", "------", "-----------"))
	for i in range(len(all_gd_detectors)):
		print(fmt % (all_gd_detectors[i]['AccountId'], all_gd_detectors[i]['Region'], all_gd_detectors[i]['DetectorIds']))

print(ERASE_LINE)
print("We scanned {} accounts and {} regions totalling {} possible areas for resources.".format(len(ChildAccounts), len(gd_regions), len(ChildAccounts)*len(gd_regions)))
print("Found {} Invites across {} accounts across {} regions".format(len(all_gd_invites), len(ChildAccounts), len(gd_regions)))
print("Found {} Detectors across {} profiles across {} regions".format(NumObjectsFound, len(ChildAccounts), len(gd_regions)))
print()

if DeletionRun and not ForceDelete:
	ReallyDelete = (input("Deletion of Guard Duty detectors has been requested. Are you still sure? (y/n): ") == 'y')
else:
	ReallyDelete = False

if DeletionRun and (ReallyDelete or ForceDelete):
	MemberList = []
	logging.warning("Deleting all invites")
	for y in range(len(all_gd_invites)):
		session_gd_child = boto3.Session(
			aws_access_key_id=all_gd_invites[y]['AccessKeyId'],
			aws_secret_access_key=all_gd_invites[y]['SecretAccessKey'],
			aws_session_token=all_gd_invites[y]['SessionToken'],
			region_name=all_gd_invites[y]['Region'])
		client_gd_child = session_gd_child.client('guardduty')
		# Delete Invitations
		try:
			print(ERASE_LINE, f"Deleting invite for Account {all_gd_invites[y]['AccountId']}", end="\r")
			Output = client_gd_child.delete_invitations(
				AccountIds=[all_gd_invites[y]['AccountId']]
			)
		except Exception as e:
			if e.response['Error']['Code'] == 'BadRequestException':
				logging.warning("Caught exception 'BadRequestException', handling the exception...")
				pass
			else:
				print("Caught unexpected error regarding deleting invites")
				pprint.pprint(e)
				sys.exit(9)
	print("Removed {} GuardDuty Invites".format(len(all_gd_invites)))
	for y in range(len(all_gd_detectors)):
		logging.info(f"Deleting detector-id: {all_gd_detectors[y]['DetectorIds']} from account {all_gd_detectors[y]['AccountId']} in region {all_gd_detectors[y]['Region']}")
		print(f"Deleting detector in account {all_gd_detectors[y]['AccountId']} in region {all_gd_detectors[y]['Region']}")
		session_gd_child = boto3.Session(
			aws_access_key_id=all_gd_detectors[y]['AccessKeyId'],
			aws_secret_access_key=all_gd_detectors[y]['SecretAccessKey'],
			aws_session_token=all_gd_detectors[y]['SessionToken'],
			region_name=all_gd_detectors[y]['Region'])
		client_gd_child = session_gd_child.client('guardduty')
		# List Members
		Member_Dict = client_gd_child.list_members(
			DetectorId=str(all_gd_detectors[y]['DetectorIds'][0]), OnlyAssociated='FALSE')['Members']
		for i in range(len(Member_Dict)):
			MemberList.append(Member_Dict[i]['AccountId'])
		# MemberList.append('704627748197')
		try:
			Output = 0
			client_gd_child.disassociate_from_master_account(
				DetectorId=str(all_gd_detectors[y]['DetectorIds'][0])
			)
		except Exception as e:
			if e.response['Error']['Code'] == 'BadRequestException':
				logging.warning("Caught exception 'BadRequestException', handling the exception...")
				pass
		# Disassociate Members
		if MemberList:  # This handles the scenario where the detectors aren't associated with the Master
			client_gd_child.disassociate_members(AccountIds=MemberList,
			                                     DetectorId=str(all_gd_detectors[y]['DetectorIds'][0])
			                                     )
			logging.warning(f"Account {str(all_gd_detectors[y]['AccountId'])} has been disassociated from master account")
			client_gd_child.delete_members(
				AccountIds=[all_gd_detectors[y]['AccountId']], DetectorId=str(all_gd_detectors[y]['DetectorIds'][0]))
			logging.warning(f"Account {str(all_gd_detectors[y]['AccountId'])} has been deleted from master account")
		client_gd_child.delete_detector(DetectorId=str(all_gd_detectors[y]['DetectorIds'][0]))
		logging.warning(f"Detector {str(all_gd_detectors[y]['DetectorIds'][0])} has been deleted from child account {str(all_gd_detectors[y]['AccountId'])}")
		"""
		if StacksFound[y][3] == 'DELETE_FAILED':
			response=Inventory_Modules.delete_stack(StacksFound[y][0],StacksFound[y][1],StacksFound[y][2],RetainResources=True,ResourcesToRetain=["MasterDetector"])
		else:
			response=Inventory_Modules.delete_stack(StacksFound[y][0],StacksFound[y][1],StacksFound[y][2])
		"""

print()
print("Thank you for using this tool")
