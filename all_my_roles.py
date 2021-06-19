#!/usr/bin/env python3

import Inventory_Modules
import boto3
import argparse
from colorama import init
from botocore.exceptions import ClientError

import logging

init()

parser = argparse.ArgumentParser(
	prefix_chars='-+/',
	description="We're going to find all roles within any of the accounts we have access to, given the profile provided.")
parser.add_argument(
	"-p", "--profile",
	dest="pProfile",
	metavar="profile to use",
	help="You need to specify a profile that represents the ROOT account.")
parser.add_argument(
	"-r", "--role",
	dest="pRole",
	metavar="specific role to find",
	default=None,
	help="Please specify the role you're searching for")
parser.add_argument(
	"+d", "--delete",
	dest="pDelete",
	action="store_const",
	const=True,
	default=False,
	help="Whether you'd like to delete that specified role.")
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
	help="Print debugging statements",
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
pRole = args.pRole
pDelete = args.pDelete
logging.basicConfig(level=args.loglevel,
                    format="[%(filename)s:%(lineno)s:%(levelname)s - %(funcName)20s() ] %(""message)s")

##########################
ERASE_LINE = '\x1b[2K'
##########################


def delete_role(fRoleList):
	iam_session = boto3.Session(
		aws_access_key_id=fRoleList['aws_access_key_id'],
		aws_secret_access_key=fRoleList['aws_secret_access_key'],
		aws_session_token=fRoleList['aws_session_token'],
		region_name='us-east-1'
	)
	iam_client = iam_session.client('iam')
	try:
		attached_role_policies = iam_client.list_attached_role_policies(
			RoleName=fRoleList['RoleName']
		)['AttachedPolicies']
		for i in range(len(attached_role_policies)):
			response = iam_client.detach_role_policy(
				RoleName=fRoleList['RoleName'],
				PolicyArn=attached_role_policies[i]['PolicyArn']
			)
		inline_role_policies = iam_client.list_role_policies(RoleName=fRoleList['RoleName'])['PolicyNames']
		for i in range(len(inline_role_policies)):
			response = iam_client.delete_role_policy(
				RoleName=fRoleList['RoleName'],
				PolicyName=inline_role_policies[i]['PolicyName']
			)
		response = iam_client.delete_role(
			RoleName=fRoleList['RoleName']
		)
		return (True)
	except ClientError as my_Error:
		print(my_Error)
		return (False)
##########################


ChildAccounts = Inventory_Modules.find_child_accounts2(pProfile)

print()
if pRole is not None:
	print(f"Looking for a specific role called {pRole}")
	print()
fmt = '%-15s %-42s'
print(fmt % ("Account Number", "Role Name"))
print(fmt % ("--------------", "---------"))
Roles = []
SpecifiedRoleNum = 0
DeletedRoles = 0
for account in ChildAccounts:
	try:
		RoleNum = 0
		account_credentials, role = Inventory_Modules.get_child_access2(pProfile, account['AccountId'])
		if role.find("failed") > 0:
			logging.error("Access to member account %s failed...", account['AccountId'])
			continue
		account_credentials['AccountNumber'] = account['AccountId']
		logging.info("Connecting to %s with %s role", account['AccountId'], role)
		print(ERASE_LINE, f"Checking Account {account_credentials['AccountNumber']}", end="")
	except ClientError as my_Error:
		if str(my_Error).find("AuthFailure") > 0:
			print(f"{pProfile}: Authorization Failure for account {account['AccountId']}")
		continue
	iam_session = boto3.Session(
		aws_access_key_id=account_credentials['AccessKeyId'],
		aws_secret_access_key=account_credentials['SecretAccessKey'],
		aws_session_token=account_credentials['SessionToken'],
		region_name='us-east-1'
	)
	iam_client = iam_session.client('iam')
	try:
		response = iam_client.list_roles()
		for i in range(len(response['Roles'])):
			Roles.append({
				'aws_access_key_id': account_credentials['AccessKeyId'],
				'aws_secret_access_key': account_credentials['SecretAccessKey'],
				'aws_session_token': account_credentials['SessionToken'],
				'AccountId': account_credentials['AccountNumber'],
				'RoleName': response['Roles'][i]['RoleName']
			})
		RoleNum = len(response['Roles'])
		while response['IsTruncated']:
			response = iam_client.list_roles(Marker=response['Marker'])
			for i in range(len(response['Roles'])):
				Roles.append({
					'AccountId': account_credentials['AccountNumber'],
					'RoleName': response['Roles'][i]['RoleName']
				})
				RoleNum += len(response['Roles'])
		print(f" - Found {RoleNum} roles", end="\r")
	except ClientError as my_Error:
		if str(my_Error).find("AuthFailure") > 0:
			print(f"{pProfile}: Authorization Failure for account {account['AccountId']}")

RoleNum = 0
if (pRole is None):
	for i in range(len(Roles)):
		print(fmt % (Roles[i]['AccountId'], Roles[i]['RoleName']))
		RoleNum += 1
elif pRole is not None:
	for i in range(len(Roles)):
		RoleNum += 1
		logging.info(f"In account {Roles[i]['AccountId']}: Found Role {Roles[i]['RoleName']} : Looking for role {pRole}")
		if Roles[i]['RoleName'].find(pRole) >= 0:
			print(fmt % (Roles[i]['AccountId'], Roles[i]['RoleName']), end="")
			SpecifiedRoleNum += 1
			if pDelete:
				delete_role(Roles[i])
				print(" - deleted", end="")
				DeletedRoles += 1
			print()

print()
if (pRole is None):
	print("Found {} roles across {} accounts".format(RoleNum, len(ChildAccounts)))
else:
	print("Found {} in {} of {} accounts".format(pRole, SpecifiedRoleNum, len(ChildAccounts)))
	if pDelete:
		print(f"     And we deleted it {DeletedRoles} times")
print()
print("Thanks for using this script...")
print()
