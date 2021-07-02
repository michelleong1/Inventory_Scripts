#!/usr/bin/env python3

import sys

import boto3

import Inventory_Modules
import vpc_modules
import argparse
from colorama import init, Fore
from botocore.exceptions import ClientError
from account_class import aws_acct_access

import logging

init()

parser = argparse.ArgumentParser(
	description="We\'re going to determine whether this new account satisfies all the pre-reqs to be adopted by the Landing Zone.",
	prefix_chars='-+/')
parser.add_argument(
	"--explain",
	dest="pExplain",
	const=True,
	default=False,
	action="store_const",
	help="This flag prints out the explanation of what this script would do.")
parser.add_argument(
	"-p", "--profile",
	dest="pProfile",
	metavar="profile of Management Account within the Organization",
	default="default",
	help="To specify a specific profile, use this parameter. Default will be your default profile.")
parser.add_argument(
	"-a", "--account",
	dest="pChildAccountId",
	metavar="New Account to be adopted into LZ",
	default="123456789012",
	required=True,
	help="This is the account number of the account you're checking, to see if it can be adopted into the ALZ.")
parser.add_argument(
	"-q", "--quick",
	dest="Quick",
	metavar="Shortcut the checking to only a single region",
	const=True,
	default=False,
	action="store_const",
	help="This flag only checks 'us-east-1', so makes the whole script run really fast.")
parser.add_argument(
	"+fix", "+delete",
	dest="FixRun",
	const=True,
	default=False,
	action="store_const",
	help="This will fix the issues found. If default VPCs must be deleted, you'll be asked to confirm.")
parser.add_argument(
	"+force",
	dest="pVPCConfirm",
	const=True,
	default=False,
	action="store_const",
	help="This will delete the default VPCs found with NO confirmation. You still have to specify the +fix too")
# TODO: There should be an additional parameter here that would take a role name for access into the account,
#  since it's likely that users won't be able to use the AWSControlTowerExecution role
parser.add_argument(
	'-v',
	help="Be verbose",
	action="store_const",
	dest="loglevel",
	const=logging.ERROR,        # args.loglevel = 40
	default=logging.CRITICAL)   # args.loglevel = 50
parser.add_argument(
	'-vv', '--verbose',
	help="Be MORE verbose",
	action="store_const",
	dest="loglevel",
	const=logging.WARNING,      # args.loglevel = 30
	default=logging.CRITICAL)   # args.loglevel = 50
parser.add_argument(
	'-vvv', '--info',
	help="Print debugging statements",
	action="store_const",
	dest="loglevel",
	const=logging.INFO,         # args.loglevel = 20
	default=logging.CRITICAL)   # args.loglevel = 50
parser.add_argument(
	'-d', '--debug',
	help="Print LOTS of debugging statements",
	action="store_const",
	dest="loglevel",
	const=logging.DEBUG,        # args.loglevel = 10
	default=logging.CRITICAL)   # args.loglevel = 50
args = parser.parse_args()

Quick = args.Quick
pProfile = args.pProfile
pChildAccountId = args.pChildAccountId
verbose = args.loglevel
FixRun = args.FixRun
pExplain = args.pExplain
pVPCConfirm = args.pVPCConfirm
logging.basicConfig(level=args.loglevel, format="[%(filename)s:%(lineno)s:%(levelname)s - %(funcName)30s() ] %(message)s")
# This is hard-coded, because this is the listing of regions that are supported by Automated Landing Zone.
if Quick:
	RegionList = ['us-east-1']
else:
	# RegionList = Inventory_Modules.get_ec2_regions('all', pProfile)
	# ap-northeast-3 doesn't support Config (and therefore doesn't support ALZ), but is a region that is normally included within EC2. Therefore - this is easier.
	RegionList = ['ap-northeast-1', 'ap-northeast-2', 'ap-south-1', 'ap-southeast-1', 'ap-southeast-2', 'ca-central-1', 'eu-central-1', 'eu-north-1', 'eu-west-1', 'eu-west-2', 'eu-west-3', 'sa-east-1', 'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']

ERASE_LINE = '\x1b[2K'

ExplainMessage = """

0. The Child account MUST allow the Management account access into the Child IAM role called "AWSCloudFormationStackSetExecutionRole"
0a. There must be an "AWSCloudFormationStackSetExecution" or "AWSControlTowerExecutionRole" role present in the account so that StackSets can assume it and deploy stack instances. This role must trust the Organizations Management account. In LZ the account is created with that role name so stacksets just works. You can add this role manually via CloudFormation in the existing account. [I did this as a step 0]
0b. STS must be active in all regions. You can check from the Account Settings page in IAM. Since we're using STS to connect to the account from the Management Account, this requirement is checked by successfully completing step 0.

1. The account must not contain any resources/config associated with the Default VPCs in ANY region e.g. security groups cannot exist associated with the Default VPC. Default VPCs will be deleted in the account in all regions, if they contain some dependency (usually a Security Group or an EIP) then deleting the VPC fails and the deployment rolls back. You can either manually delete them all or verify there are no dependencies, in some cases manually deleting them all is faster than roll back.

2. There must be no active config channel and recorder in the account as “there can be only one” of each. This must also be deleted via CLI, not console, switching config off in the console is NOT good enough and just disables it. To Delete the delivery channel and the configuration recorder (can be done via CLI and Python script only):
aws configservice describe-delivery-channels
aws configservice describe-delivery-channel-status
aws configservice describe-configuration-recorders
aws configservice stop-configuration-recorder --configuration-recorder-name <NAME-FROM-DESCRIBE-OUTPUT>
aws configservice delete-delivery-channel --delivery-channel-name <NAME-FROM-DESCRIBE-OUTPUT>
aws configservice delete-configuration-recorder --configuration-recorder-name <NAME-FROM-DESCRIBE-OUTPUT

3. The account must not have a Cloudtrail Trail name the same name as the LZ Trail ("AWS-Landing-Zone-BaselineCloudTrail")

4. The account must not have a pending guard duty invite. You can check from the Guard Duty Console

5. The account must be part of the Organization and the email address being entered into the LZ parameters must match the account. If you try to add an email from an account which is not part of the Org, you will get an error that you are not using a unique email address. If it’s part of the Org, LZ just finds the account and uses the CFN roles.
- If the existing account is to be imported as a Core Account, modify the manifest.yaml file to use it.
- If the existing account will be a child account in the Organization, use the AVM launch template through Service Catalog and enter the appropriate configuration parameters.

6. The existing account can not be in any of the LZ-managed Organizations OUs. By default, these OUs are Core and Applications, but the customer may have chosen different or additional OUs to manage by LZ.

"""
print()
if pExplain:
	print(ExplainMessage)
	sys.exit("Exiting after Script Explanation...")

# TODO: This is supposed to be the recommended Trust Policy for the cross-account role access,
#  so that we can recommend people add it to their "AWSCloudFormationStackSetExecutionRole"
json_formatted_str_TP = ""


##########
def _initdict(StepCount):
	fProcessStatus = {'ChildIsReady': True, 'IssuesFound': 0, 'IssuesFixed': 0}
	for m in range(StepCount):
		Step = f"Step{str(m)}"
		fProcessStatus[Step] = {}
		fProcessStatus[Step]['Success'] = True
		fProcessStatus[Step]['IssuesFound'] = 0
		fProcessStatus[Step]['IssuesFixed'] = 0
	return(fProcessStatus)
###########


ProcessStatus = _initdict(6)
# Step 0 -
# 0. The Child account MUST allow the Management account access into the Child IAM role called "AWSCloudFormationStackSetExecutionRole"

print("This script does 6 things... ")
print(f"{Fore.BLUE}  0.{Fore.RESET} Checks to ensure you have the necessary cross-account role access to the child account.")
print(f"{Fore.BLUE}  1.{Fore.RESET} Checks to ensure the {Fore.RED}Default VPCs {Fore.RESET}in each region are deleted")
if FixRun and not pVPCConfirm:
	print(f"{Fore.BLUE}	You've asked to delete any default VPCs we find - with confirmation on each one.{Fore.RESET}")
elif FixRun and pVPCConfirm:
	print()
	print(f"{Fore.RED}	You've asked to delete any default VPCs we find - WITH NO CONFIRMATION on each one.{Fore.RESET}")
	print()
elif pVPCConfirm and not FixRun:
	print()
	print(f"{Fore.BLUE}	You asked us to delete the default VPCs with no confirmation, but didn't provide the '+fixrun' parameter, so we're proceeding with NOT deleting. You can safely interupt this script and run it again with the necessary parameters.{Fore.RESET}")
	print()
print(f"{Fore.BLUE}  2.{Fore.RESET} Checks the child account in each of the regions")
print(f"     to see if there's already a {Fore.RED}Config Recorder and Delivery Channel {Fore.RESET}enabled...")
print(f"{Fore.BLUE}  3.{Fore.RESET} Checks that there isn't a duplicate {Fore.RED}CloudTrail{Fore.RESET} trail in the account.")
print(f"{Fore.BLUE}  4.{Fore.RESET} Checks to see if {Fore.RED}GuardDuty{Fore.RESET} has been enabled for this child account.")
print("     If it has been, it needs to be deleted before we can adopt this new account")
print("     into the Org's Automated Landing Zone.")
print(f"{Fore.BLUE}  5.{Fore.RESET} This child account {Fore.RED}must exist{Fore.RESET} within the Parent Organization.")
print("     If it doesn't - then you must move it into this Org")
print("     (this script can't do that for you).")
print()
print("Since this script is fairly new - All comments or suggestions are enthusiastically encouraged")
print()

role = 'failed'
if pProfile is None:
	session_obj = boto3.Session()
elif pProfile is not None:
	session_obj = boto3.Session(profile_name=pProfile)
aws_account = aws_acct_access(session_obj)
try:
	account_credentials, role = Inventory_Modules.get_child_access2(pProfile, pChildAccountId)
	if role.find("failed") > 0:
		print(Fore.RED, "We weren't able to connect to the Child Account from this Management Account. Please check the role Trust Policy and re-run this script.", Fore.RESET)
		print(f"The following list of roles were tried, but none were allowed access to account {pChildAccountId} using the {pProfile} profile")
		print(Fore.RED, role, Fore.RESET)
		ProcessStatus['Step0']['Success'] = False
		sys.exit("Exiting due to cross-account Auth Failure")
except ClientError as my_Error:
	if str(my_Error).find("AuthFailure") > 0:
		# TODO: This whole section is waiting on an enhancement. Until then, we have to assume that ProServe or someone familiar with Control Tower is running this script
		print(f"{pProfile}: Authorization Failure for account {pChildAccountId}")
		print(f"The child account MUST allow access into the IAM role {role} from the Organization's Master Account for the rest of this script (and the overall migration) to run.")
		print("You must add the following lines to the Trust Policy of that role in the child account")
		print(json_formatted_str_TP)
		print(my_Error)
		ProcessStatus['Step0']['Success'] = False
		sys.exit("Exiting due to Authorization Failure...")
	elif str(my_Error).find("AccessDenied") > 0:
		# TODO: This whole section is waiting on an enhancement. Until then, we have to assume that ProServe or someone familiar with Control Tower is running this script
		print(f"{pProfile}: Access Denied Failure for account {pChildAccountId}")
		print(f"The child account MUST allow access into the IAM role {role} from the Organization's Master Account for the rest of this script (and the overall migration) to run.")
		print("You must add the following lines to the Trust Policy of that role in the child account")
		print(json_formatted_str_TP)
		print(my_Error)
		ProcessStatus['Step0']['Success'] = False
		sys.exit("Exiting due to Access Denied Failure...")
	else:
		print(f"{pProfile}: Other kind of failure for account {pChildAccountId}")
		print(my_Error)
		ProcessStatus['Step0']['Success'] = False
		sys.exit("Exiting...")

account_credentials['AccountNumber'] = pChildAccountId
logging.error("Was able to successfully connect using the credentials... ")
print()
calling_creds = Inventory_Modules.find_calling_identity(pProfile)
print(f"Confirmed the role{Fore.GREEN}", role, f"{Fore.RESET}exists in account{Fore.GREEN}", pChildAccountId, f"{Fore.RESET}and trusts{Fore.GREEN}", f"{calling_creds['Short']}{Fore.RESET}", "within the Master Account")
print(f"{Fore.GREEN}** Step 0 completed without issues{Fore.RESET}")
print()

# Step 1
# This part will find and delete the Default VPCs in each region for the child account. We only delete if you provided that in the parameters list.
DefaultVPCs = []
try:
	print(f"Checking account {pChildAccountId} for default VPCs in any region")
	for region in RegionList:
		print(ERASE_LINE, f"Checking account {pChildAccountId} in region {region}", "for", f"{Fore.RED}default VPCs{Fore.RESET}", end='\r')
		logging.info("Looking for Default VPCs in account %s from Region %s", pChildAccountId, region)
		DefaultVPC = Inventory_Modules.find_account_vpcs(account_credentials, region, True)
		if len(DefaultVPC['Vpcs']) > 0:
			DefaultVPCs.append({
				'VPCId': DefaultVPC['Vpcs'][0]['VpcId'],
				'AccountID': pChildAccountId,
				'Region': region
			})
			ProcessStatus['Step1']['IssuesFound'] += 1
			ProcessStatus['Step1']['Success'] = False
except ClientError as my_Error:
	logging.warning("Failed to identify the Default VPCs in the region properly")
	ProcessStatus['Step1']['Success'] = False
	print(my_Error)

print(ERASE_LINE, end='\r')
for i in range(len(DefaultVPCs)):
	logging.info(f"I found a default VPC for account {DefaultVPCs[i]['AccountID']} in region {DefaultVPCs[i]['Region']}")
	if FixRun:
		logging.warning("Deleting VpcId %s in account %s in region %s", DefaultVPCs[i]['VPCId'], DefaultVPCs[i]['AccountID'], DefaultVPCs[i]['Region'])
		try:    # confirm the user really want to delete the VPC. This is irreversible
			if pVPCConfirm:
				ReallyDelete = True
			else:
				ReallyDelete = (input(f"Deletion of {DefaultVPCs[i]['Region']} default VPC has been requested. Are you still sure? (y/n): ") in ['y', 'Y'])
			if ReallyDelete:
				DelVPC_Success = (vpc_modules.del_vpc(account_credentials, DefaultVPCs[i]['VPCId'], DefaultVPCs[i]['Region']) == 0)
				if DelVPC_Success:
					ProcessStatus['Step1']['IssuesFixed'] += 1
				else:
					print("Something went wrong with the VPC Deletion")
					ProcessStatus['Step1']['Success'] = False
					sys.exit(9)
			else:
				logging.warning("User answered False to the 'Are you sure' question")
				print(f"Skipping VPC ID {DefaultVPCs[i]['VPCId']} in account {DefaultVPCs[i]['AccountID']} in region {DefaultVPCs[i]['Region']}")
				ProcessStatus['Step1']['Success'] = False
		except ClientError as my_Error:
			logging.error("Failed to delete the Default VPCs in the region properly")
			ProcessStatus['Step1']['Success'] = False
			print(my_Error)

print()
if ProcessStatus['Step1']['Success']:
	print(f"{ERASE_LINE + Fore.GREEN}** Step 1 completed with no issues{Fore.RESET}")
elif ProcessStatus['Step1']['IssuesFound'] - ProcessStatus['Step1']['IssuesFixed'] == 0:
	print(f"{ERASE_LINE + Fore.GREEN}** Step 1 found {ProcessStatus['Step1']['IssuesFound']} issues, but they were fixed by deleting the default vpcs{Fore.RESET}")
	ProcessStatus['Step1']['Success'] = True
elif (ProcessStatus['Step1']['IssuesFound'] > ProcessStatus['Step1']['IssuesFixed']):
	print(f"{ERASE_LINE + Fore.RED}** Step 1 completed, but there were {ProcessStatus['Step1']['IssuesFound'] - ProcessStatus['Step1']['IssuesFixed']} vpcs that couldn't be fixed{Fore.RESET}")
else:
	print(f"{ERASE_LINE + Fore.RED}** Step 1 completed with blockers found{Fore.RESET}")

# Step 2
	# This part will check the Config Recorder and  Delivery Channel. If they have one, we need to delete it, so we can create another. We'll ask whether this is ok before we delete.
ConfigList = []
DeliveryChanList = []
try:
	# RegionList=Inventory_Modules.get_service_regions('config', 'all')
	print(f"Checking account {pChildAccountId} for Config Recorders and Delivery Channels in any region")
	# TODO: Need to find a way to gracefully handle the error processing of opt-in regions.
	# Until then - we're using a hard-coded listing of regions, instead of dynamically finding those.
	# RegionList.remove('me-south-1')	# Opt-in region, which causes a failure if we check and it's not opted-in
	# RegionList.remove('ap-east-1')	# Opt-in region, which causes a failure if we check and it's not opted-in
	for region in RegionList:
		print(ERASE_LINE, f"Checking account {pChildAccountId} in region {region} for Config Recorder", end='\r')
		logging.info("Looking for Config Recorders in account %s from Region %s", pChildAccountId, region)
		# ConfigRecorder=client_cfg.describe_configuration_recorders()
		ConfigRecorder = Inventory_Modules.find_config_recorders(account_credentials, region)
		logging.debug("Tried to capture Config Recorder")
		if len(ConfigRecorder['ConfigurationRecorders']) > 0:
			ConfigList.append({
				'Name': ConfigRecorder['ConfigurationRecorders'][0]['name'],
				'roleARN': ConfigRecorder['ConfigurationRecorders'][0]['roleARN'],
				'AccountID': pChildAccountId,
				'Region': region
			})
		print(ERASE_LINE, f"Checking account {pChildAccountId} in region {region} for Delivery Channel", end='\r')
		DeliveryChannel = Inventory_Modules.find_delivery_channels(account_credentials, region)
		logging.debug("Tried to capture Delivery Channel")
		if len(DeliveryChannel['DeliveryChannels']) > 0:
			DeliveryChanList.append({
				'Name': DeliveryChannel['DeliveryChannels'][0]['name'],
				'AccountID': pChildAccountId,
				'Region': region
			})
	logging.error("Checked account %s in %s regions. Found %s issues with Config Recorders and Delivery Channels", pChildAccountId, len(RegionList), len(ConfigList)+len(DeliveryChanList))
except ClientError as my_Error:
	logging.warning("Failed to capture Config Recorder and Delivery Channels")
	ProcessStatus['Step2']['Success'] = False
	print(my_Error)

for i in range(len(ConfigList)):
	logging.error(f"{Fore.RED}Found a config recorder for account %s in region %s", ConfigList[i]['AccountID'], ConfigList[i]['Region']+Fore.RESET)
	ProcessStatus['Step2']['Success'] = False
	ProcessStatus['Step2']['IssuesFound'] += 1
	if FixRun:
		logging.warning("Deleting %s in account %s in region %s", ConfigList[i]['Name'], ConfigList[i]['AccountID'], ConfigList[i]['Region'])
		DelConfigRecorder = Inventory_Modules.del_config_recorder(account_credentials, ConfigList[i]['Region'], ConfigList[i]['Name'])
		# We assume the process worked. We should probably NOT assume this.
		ProcessStatus['Step2']['IssuesFixed'] += 1
for i in range(len(DeliveryChanList)):
	logging.error(f"{Fore.RED}I found a delivery channel for account %s in region %s", DeliveryChanList[i]['AccountID'], DeliveryChanList[i]['Region']+Fore.RESET)
	ProcessStatus['Step2']['Success'] = False
	ProcessStatus['Step2']['IssuesFound'] += 1
	if FixRun:
		logging.warning("Deleting %s in account %s in region %s", DeliveryChanList[i]['Name'], DeliveryChanList[i]['AccountID'], DeliveryChanList[i]['Region'])
		DelDeliveryChannel = Inventory_Modules.del_delivery_channel(account_credentials, ConfigList[i]['Region'], DeliveryChanList[i]['Name'])
		# We assume the process worked. We should probably NOT assume this.
		ProcessStatus['Step2']['IssuesFixed'] += 1

if ProcessStatus['Step2']['Success']:
	print(f"{ERASE_LINE + Fore.GREEN}** Step 2 completed with no issues{Fore.RESET}")
elif ProcessStatus['Step2']['IssuesFound'] - ProcessStatus['Step2']['IssuesFixed'] == 0:
	print(f"{ERASE_LINE + Fore.GREEN}** Step 2 found {ProcessStatus['Step2']['IssuesFound']} issues, but they were fixed by deleting the existing Config Recorders and Delivery Channels{Fore.RESET}")
	ProcessStatus['Step2']['Success'] = True
elif (ProcessStatus['Step2']['IssuesFound'] > ProcessStatus['Step2']['IssuesFixed']):
	print(f"{ERASE_LINE + Fore.RED}** Step 2 completed, but there were {ProcessStatus['Step2']['IssuesFound'] - ProcessStatus['Step2']['IssuesFixed']} items found that couldn't be deleted{Fore.RESET}")
else:
	print(f"{ERASE_LINE + Fore.RED}** Step 2 completed with blockers found{Fore.RESET}")
print()
# Step 3
# 3. The account must not have a Cloudtrail Trail name the same name as the LZ Trail ("AWS-Landing-Zone-BaselineCloudTrail")
CTtrails2 = []
trailname = None
try:
	print(f"Checking account {pChildAccountId} for a specially named CloudTrail in all regions")
	for region in RegionList:
		print(ERASE_LINE, f"Checking account {pChildAccountId} in region {region} for CloudTrail trails", end='\r')
		CTtrails, trailname = Inventory_Modules.find_cloudtrails(account_credentials, region, ['AWS-Landing-Zone-BaselineCloudTrail'])
		if len(CTtrails['trailList']) > 0:
			logging.error("Unfortunately, we've found a CloudTrail log named %s in account %s in the %s region, which means we'll have to delete it before this account can be adopted.", trailname, pChildAccountId, region)
			CTtrails['trailList'][0]['region'] = region
			CTtrails2.append(CTtrails['trailList'][0])
			ProcessStatus['Step3']['Success'] = False
except ClientError as my_Error:
	print(my_Error)
	ProcessStatus['Step3']['Success'] = False

for i in range(len(CTtrails2)):
	logging.error(f"{Fore.RED}Found a CloudTrail trail for account %s in region %s named %s ", pChildAccountId, CTtrails2[i]['region'], trailname+Fore.RESET)
	ProcessStatus['Step3']['IssuesFound'] += 1
	if FixRun:
		try:
			logging.error("CloudTrail trail deletion commencing...")
			delresponse = Inventory_Modules.del_cloudtrails(account_credentials, CTtrails2[i]['region'], CTtrails2[i]['TrailARN'])
			ProcessStatus['Step3']['IssuesFixed'] += 1
		except ClientError as my_Error:
			print(my_Error)

if ProcessStatus['Step3']['Success']:
	print(f"{ERASE_LINE + Fore.GREEN}** Step 3 completed with no issues{Fore.RESET}")
elif ProcessStatus['Step3']['IssuesFound'] - ProcessStatus['Step3']['IssuesFixed'] == 0:
	print(f"{ERASE_LINE + Fore.GREEN}** Step 3 found {ProcessStatus['Step3']['IssuesFound']} issues, but they were fixed by deleting the existing CloudTrail trail names{Fore.RESET}")
	ProcessStatus['Step3']['Success'] = True
elif (ProcessStatus['Step3']['IssuesFound'] > ProcessStatus['Step3']['IssuesFixed']):
	print(f"{ERASE_LINE + Fore.RED}** Step 3 completed, but there were {ProcessStatus['Step3']['IssuesFound'] - ProcessStatus['Step3']['IssuesFixed']} trail names found that couldn't be deleted{Fore.RESET}")
else:
	print(f"{ERASE_LINE + Fore.RED}** Step 3 completed with blockers found{Fore.RESET}")
print()
# Step 4 - handled by Step 0
# 4. There must be an AWSCloudFormationStackSetExecution role present in the account so that StackSets can assume it and deploy stack instances. This role must trust the Organizations Master account. In LZ the account is created with that role name so stacksets just works. You can add this role manually via CloudFormation in the existing account.

# Step 4
# 4. The account must not have a pending guard duty invite. You can check from the Guard Duty Console
GDinvites2 = []
try:
	print(f"Checking account {pChildAccountId} for any GuardDuty invites")
	for region in RegionList:
		logging.error(f"{ERASE_LINE}Checking account %s in region %s for", pChildAccountId, f"{region + Fore.RED} GuardDuty{Fore.RESET} invitations")
		logging.error("Checking account %s in region %s for GuardDuty invites", pChildAccountId, region)
		GDinvites = Inventory_Modules.find_gd_invites(account_credentials, region)
		if len(GDinvites) > 0:
			for x in range(len(GDinvites['Invitations'])):
				logging.warning("GD Invite: %s", str(GDinvites['Invitations'][x]))
				logging.error("Unfortunately, we've found a GuardDuty invitation for account %s in the %s region from account %s, which means we'll have to delete it before this account can be adopted.", pChildAccountId, region, GDinvites['Invitations'][x]['AccountId'])
				ProcessStatus['Step4']['IssuesFound'] += 1
				GDinvites2.append({
					'AccountId': GDinvites['Invitations'][x]['AccountId'],
					'InvitationId': GDinvites['Invitations'][x]['InvitationId'],
					'Region': region
				})
except ClientError as my_Error:
	print(my_Error)
	ProcessStatus['Step4']['Success'] = False

for i in range(len(GDinvites2)):
	logging.error(f"{Fore.RED}I found a GuardDuty invitation for account %s in region %s from account %s ", pChildAccountId, GDinvites2[i]['Region'], GDinvites2[i]['AccountId']+Fore.RESET)
	ProcessStatus['Step4']['IssuesFound'] += 1
	ProcessStatus['Step4']['Success'] = False
	if FixRun:
		for x in range(len(GDinvites2)):
			try:
				logging.warning("GuardDuty invite deletion commencing...")
				delresponse = Inventory_Modules.delete_gd_invites(account_credentials, GDinvites2[x]['Region'], GDinvites2[x]['AccountId'])
				ProcessStatus['Step4']['IssuesFixed'] += 1
				# We assume the process worked. We should probably NOT assume this.
			except ClientError as my_Error:
				print(my_Error)

if ProcessStatus['Step4']['Success']:
	print(f"{ERASE_LINE + Fore.GREEN}** Step 4 completed with no issues{Fore.RESET}")
elif ProcessStatus['Step4']['IssuesFound'] - ProcessStatus['Step4']['IssuesFixed'] == 0:
	print(f"{ERASE_LINE + Fore.GREEN}** Step 4 found {ProcessStatus['Step4']['IssuesFound']} guardduty invites, but they were deleted{Fore.RESET}")
	ProcessStatus['Step4']['Success'] = True
elif (ProcessStatus['Step4']['IssuesFound'] > ProcessStatus['Step4']['IssuesFixed']):
	print(f"{ERASE_LINE + Fore.RED}** Step 4 completed, but there were {ProcessStatus['Step4']['IssuesFound'] - ProcessStatus['Step4']['IssuesFixed']} guardduty invites found that couldn't be deleted{Fore.RESET}")
else:
	print(f"{ERASE_LINE + Fore.RED}** Step 4 completed with blockers found{Fore.RESET}")
print()
# Step 6
# 6. STS must be active in all regions. You can check from the Account Settings page in IAM.
"""
We would have already verified this - since we've used STS to connect to each region already for the previous steps.
"""
# Step 7
'''
5. The account must be part of the Organization and the email address being entered into the LZ parameters must match the account. If 	you try to add an email from an account which is not part of the Org, you will get an error that you are not using a unique email address. If it’s part of the Org, LZ just finds the account and uses the CFN roles.
- If the existing account is to be imported as a Core Account, modify the manifest.yaml file to use it.
- If the existing account will be a child account in the Organization, use the AVM launch template through Service Catalog and enter the appropriate configuration parameters.
'''
# try:
print("Checking that the account is part of the AWS Organization.")
OrgAccounts = Inventory_Modules.find_child_accounts2(pProfile)
OrgAccountList = []
for y in range(len(OrgAccounts)):
	OrgAccountList.append(OrgAccounts[y]['AccountId'])
if not (pChildAccountId in OrgAccountList):
	print()
	print(f"Account # {pChildAccountId} is not a part of the Organization. This account needs to be moved into the Organization to be adopted into the Landing Zone tool")
	print("This is easiest done manually right now.")
	ProcessStatus['Step5']['Success'] = False
	ProcessStatus['Step5']['IssuesFound'] += 1

if ProcessStatus['Step5']['Success']:
	print(f"{ERASE_LINE + Fore.GREEN}** Step 5 completed with no issues{Fore.RESET}")
elif ProcessStatus['Step5']['IssuesFound']-ProcessStatus['Step5']['IssuesFixed'] == 0:
	print(f"{ERASE_LINE + Fore.GREEN}** Step 5 found {ProcessStatus['Step5']['IssuesFound']} issues, but we were able to move the account into the they were able to be fixed{Fore.RESET}")
	ProcessStatus['Step5']['Success'] = True
elif (ProcessStatus['Step5']['IssuesFound'] > ProcessStatus['Step5']['IssuesFixed']):
	print(f"{ERASE_LINE + Fore.RED}** Step 5 completed, but there were {ProcessStatus['Step5']['IssuesFound'] - ProcessStatus['Step5']['IssuesFixed']} blockers found that couldn't be fixed{Fore.RESET}")
else:
	print(f"{ERASE_LINE + Fore.RED}** Step 5 completed with blockers found{Fore.RESET}")
print()
# Step 6
# 6. The existing account can not be in any of the LZ-managed Organizations OUs. By default, these OUs are Core and Applications, but the customer may have chosen different or additional OUs to manage by LZ.
"""
So we'll need to verify that the parent OU of the account is the root of the organization.
"""

ChildIsReady = ProcessStatus['Step1']['Success'] and ProcessStatus['Step2']['Success'] and ProcessStatus['Step3']['Success'] and ProcessStatus['Step4']['Success'] and ProcessStatus['Step5']['Success']
NumberOfIssues = ProcessStatus['Step1']['IssuesFound'] + ProcessStatus['Step2']['IssuesFound'] + ProcessStatus['Step3']['IssuesFound'] + ProcessStatus['Step4']['IssuesFound'] + ProcessStatus['Step5']['IssuesFound']
NumberOfFixes = ProcessStatus['Step1']['IssuesFixed'] + ProcessStatus['Step2']['IssuesFixed'] + ProcessStatus['Step3']['IssuesFixed'] + ProcessStatus['Step4']['IssuesFixed'] + ProcessStatus['Step5']['IssuesFixed']
FixesWorked = (NumberOfIssues-NumberOfFixes == 0)
if ChildIsReady and NumberOfIssues == 0:
	print(f"{Fore.GREEN}**** We've found NO issues that would hinder the adoption of this account ****{Fore.RESET}")
elif ChildIsReady and FixesWorked:
	print(f"{Fore.GREEN}We've found and fixed{Fore.RED}", f"{NumberOfFixes}{Fore.RESET}", f"{Fore.GREEN}issues that would have otherwise blocked the adoption of this account{Fore.RESET}")
else:
	print(f"{Fore.RED}We've found {NumberOfIssues - NumberOfFixes} issues that would hinder the adoption of this account{Fore.RESET}")

# pprint.pprint(ProcessStatus)
print()
print("Thanks for using this script...")
