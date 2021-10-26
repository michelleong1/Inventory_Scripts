#!/usr/bin/env python3

"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import boto3
import Inventory_Modules
import argparse
import logging
from colorama import init, Fore
from botocore.exceptions import ClientError

init()

# UsageMsg="You can provide a level to determine whether this script considers only the 'credentials' file, the 'config' file, or both."
parser = argparse.ArgumentParser(
	description="We\'re going to find all saml identity providers within any of the child accounts within the organization.",
	prefix_chars='-+/')
parser.add_argument(
	"-p", "--profile",
	dest="pProfile",
	metavar="profile to use",
	default="default",
	help="To specify a specific profile, use this parameter. Default will be your default profile.")
parser.add_argument(
	"-k", "--skip",
	dest="pSkipAccounts",
	nargs="*",
	metavar="Accounts to leave alone",
	default=[],
	help="These are the account numbers you don't want to screw with. Likely the core accounts. Separate them by a space.")
parser.add_argument(
	"-r", "--pRegion",
	dest="pRegion",
	metavar="pRegion name string",
	default="us-east-1",
	help="String fragment of the pRegion(s) you want to check for resources.")
parser.add_argument(
	"+delete", "+forreal",
	dest="DeletionRun",
	const=True,
	default=False,
	action="store_const",
	help="This will delete the identity providers found - without any opportunity to confirm. Be careful!!")
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
	const=logging.INFO,	 # args.loglevel = 20
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
pRegion = args.pRegion
AccountsToSkip = args.pSkipAccounts
verbose = args.loglevel
DeletionRun = args.DeletionRun
logging.basicConfig(level=args.loglevel, format="[%(filename)s:%(lineno)s:%(levelname)s - %(funcName)30s() ] %(message)s")

##########################
ERASE_LINE = '\x1b[2K'

print()
fmt = '%-20s %-15s %-15s'
print(fmt % ("Account", "pRegion", "IDP Name"))
print(fmt % ("-------", "------", "--------"))
ChildAccounts = Inventory_Modules.find_child_accounts2(pProfile)
ChildAccounts = Inventory_Modules.RemoveCoreAccounts(ChildAccounts, AccountsToSkip)

NumofAccounts = len(ChildAccounts)
IdpsFound = []
for account in ChildAccounts:
	try:
		account_credentials, role_arn = Inventory_Modules.get_child_access2(pProfile, account['AccountId'])
		logging.info("Role ARN: %s" % role_arn)
		account_credentials['AccountNumber'] = account['AccountId']
	except ClientError as my_Error:
		if str(my_Error).find("AuthFailure") > 0:
			print(pProfile+": Authorization Failure for account {}".format(account['AccountId']))
		else:
			print(pProfile+": Other kind of failure for account {}".format(account['AccountId']))
			print(my_Error)
		break
	# for pRegion in pRegionList:
	try:
		Idps = Inventory_Modules.find_saml_components_in_acct(account_credentials, pRegion)
		idpNum = len(Idps)
		logging.warning("Account: %s | Region: %s | Found %s Idps", account['AccountId'], pRegion, idpNum)
		logging.warning(ERASE_LINE+Fore.RED+"Account: %s pRegion: %s Found %s Idps. Only %s accounts left to go"+Fore.RESET % (account['AccountId'], pRegion, idpNum, NumofAccounts))
	except ClientError as my_Error:
		if str(my_Error).find("AuthFailure") > 0:
			print(account['AccountId']+": Authorization Failure")
		idpNum = 0
	if idpNum > 0:
		for y in range(len(Idps)):
			logging.warning("Arn: %s", Idps[y]['Arn'])
			NameStart = Idps[y]['Arn'].find('/')+1
			logging.debug("Name starts at character: %s", NameStart)
			IdpName = Idps[y]['Arn'][NameStart:]
			print(fmt % (account['AccountId'], pRegion, IdpName))
			IdpsFound.append({
				'AccountId': account['AccountId'],
				'pRegion': pRegion,
				'IdpName': IdpName,
				'Arn': Idps[y]['Arn']})
	NumofAccounts -= 1

print(ERASE_LINE)
print(Fore.RED+"Found {} Idps across {} accounts in region {}".format(len(IdpsFound), len(ChildAccounts), pRegion)+Fore.RESET)
print()
# pprint.pprint(IdpsFound)

if DeletionRun:
	logging.warning("Deleting %s Idps", len(IdpsFound))
	for y in range(len(IdpsFound)):
		account_credentials, role_arn = Inventory_Modules.get_child_access2(pProfile, IdpsFound[y]['AccountId'])
		session_aws = boto3.Session(region_name=IdpsFound[y]['pRegion'],
									aws_access_key_id=account_credentials['AccessKeyId'],
									aws_secret_access_key=account_credentials['SecretAccessKey'],
									aws_session_token=account_credentials['SessionToken']
		)
		iam_client = session_aws.client('iam')
		print("Deleting Idp {} from account {} in pRegion {}".format(IdpsFound[y]['IdpName'], IdpsFound[y]['AccountId'], IdpsFound[y]['pRegion']))
		response = iam_client.delete_saml_provider(SAMLProviderArn=IdpsFound[y]['Arn'])

print()
print("Thanks for using this script...")
print()
