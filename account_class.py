""""
1. Accept either a single profile or multiple profiles
2. Determine if a profile (or multiple profiles) was provided
3. If a single profile was provided - determine whether it's been provided as an org account, or as a single profile
4. If the profile is of a root account and it's supposed to be for the whole Org - **note that**
	Otherwise - treat it like a standalone account (like anything else)
5. If it's a root account, we need to figure out how to find all the child accounts, and the proper roles to access them by
	5a. Find all the child accounts
	5b. Find out if any of those children are SUSPENDED and remove them from the list
	5c. Figure out the right roles to access the children by - which might be a config file, since there might be a mapping for this.
	5d. Once we have a way to access all the children, we can provide account-credentials to access the children by (but likely not the root account itself)
	5e. Call the actual target scripts - with the proper credentials (which might be a profile, or might be a session token)
6. If it's not a root account - then ... just use it as a profile

What does a script need to satisfy credentials? It needs a boto3 session. From the session, everything else can derive... yes?

So if we created a class object that represented the account:
	Attributes:
		AccountID: Its 12 digit account number
		botoClient: Access into the account (profile, or access via a root path)
		MgmntAccessRoles: The role that the root account uses to get access
		AccountStatus: Whether it's ACTIVE or SUSPENDED
		AccountType: Whether it's a root org account, a child account or a standalone account
		ParentProfile: What its parent profile name is, if available
		If it's an Org account:
			ALZ: Whether the Org is running an ALZ
			CT: Whether the Org is running CT
	Functions:
		Which regions and partitions it's enabled for
		(Could all my inventory items be an attribute of this class?)

"""

class aws_acct_access:
	"""
	Docstring that describe the class
	Class takes a session object as input
	"""
	def __init__(self, session_object=None):
		self.session = session_object
		acct_number = self.acct_num()
		AccountType = self.find_account_attr()

	def acct_num(self):
		import logging
		from botocore.exceptions import ClientError

		try:
			aws_session = self.session
			# logging.info(f"Getting creds used within profile {fProfile}")
			client_sts = aws_session.client('sts')
			response = client_sts.get_caller_identity()
			creds = response['Account']
			# creds = {'Arn': response['Arn'], 'AccountId': response['Account'],
			#          'Short': response['Arn'][response['Arn'].rfind(':') + 1:]}
		except ClientError as my_Error:
			if str(my_Error).find("UnrecognizedClientException") > 0:
				# print("{}: Security Issue".format(fProfile))
				pass
			elif str(my_Error).find("InvalidClientTokenId") > 0:
				# print("{}: Security Token is bad - probably a bad entry in config".format(fProfile))
				pass
			else:
				# print("Other kind of failure for profile {}".format(fProfile))
				print(my_Error)
				pass
			creds = "Failure"
		return (creds)

	def find_account_attr(self):
		import logging
		from botocore.exceptions import ClientError, CredentialRetrievalError

		"""
		In the case of an Org Root or Child account, I use the response directly from the AWS SDK. 
		You can find the output format here: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/organizations.html#Organizations.Client.describe_organization
		"""
		FailResponse = {'AccountType': 'Unknown', 'AccountNumber': 'None', 'Id': 'None', 'MasterAccountId': 'None'}
		session_org = self.session
		client_org = session_org.client('organizations')
		my_acct_number = self.acct_num()
		try:
			response = client_org.describe_organization()['Organization']
			response['Id'] = my_acct_number
			response['AccountNumber'] = my_acct_number
			if response['MasterAccountId'] == my_acct_number:
				response['AccountType'] = 'Root'
			else:
				response['AccountType'] = 'Child'
			return (response)
		except ClientError as my_Error:
			if str(my_Error).find("AWSOrganizationsNotInUseException") > 0:
				FailResponse['AccountType'] = 'StandAlone'
				FailResponse['Id'] = my_acct_number
				FailResponse['AccountNumber'] = my_acct_number
			elif str(my_Error).find("UnrecognizedClientException") > 0:
				logging.error(f"Security Issue with: {my_acct_number}")
			elif str(my_Error).find("InvalidClientTokenId") > 0:
				logging.error(f"{my_acct_number}: Security Token is bad - probably a bad entry in config")
			elif str(my_Error).find("AccessDenied") > 0:
				logging.error(f"{my_acct_number}: Access Denied for profile")
			pass
		except CredentialRetrievalError as my_Error:
			logging.error(f"{my_acct_number}: Failure pulling or updating credentials")
			print(my_Error)
			pass
		except:
			print("Other kind of failure")
			pass
		return (FailResponse)

	def find_child_accounts2(self):
		"""
		This is an example of the list response from this call:
			[
			{'ParentProfile':'LZRoot', 'AccountId': 'xxxxxxxxxxxx', 'AccountEmail': 'EmailAddr1@example.com', 'AccountStatus': 'ACTIVE'},
			{'ParentProfile':'LZRoot', 'AccountId': 'yyyyyyyyyyyy', 'AccountEmail': 'EmailAddr2@example.com', 'AccountStatus': 'ACTIVE'},
			{'ParentProfile':'LZRoot', 'AccountId': 'zzzzzzzzzzzz', 'AccountEmail': 'EmailAddr3@example.com', 'AccountStatus': 'SUSPENDED'}
			]
		This can be convenient for appending and removing.
		"""
		import logging
		from botocore.exceptions import ClientError

		child_accounts = []
		if self.find_account_attr()['AccountType'].lower() == 'root':
			try:
				session_org = self.session
				client_org = session_org.client('organizations')
				response = client_org.list_accounts()
				theresmore = True
				while theresmore:
					for account in response['Accounts']:
						logging.info(f"Account ID: {self.acct_num()}")
						child_accounts.append({'ParentProfile': 'Don\'t know',
						                       'AccountId': account['Id'],
						                       'AccountEmail': account['Email'],
						                       'AccountStatus': account['Status']})
					if 'NextToken' in response:
						theresmore = True
						response = client_org.list_accounts(NextToken=response['NextToken'])
					else:
						theresmore = False
				return (child_accounts)
			except ClientError as my_Error:
				logging.warning(f"Account {self.acct_num()} doesn't represent an Org Root account")
				logging.debug(my_Error)
				return ()
		elif self.find_account_attr()['AccountType'].lower() in ['standalone', 'child']:
			accountID = self.acct_num()
			child_accounts.append({'ParentProfile': 'Don\'t know',
			                       'AccountId': accountID,
			                       'AccountEmail': 'NotAnOrgRoot@example.com',
			                       # We know the account is ACTIVE because if it was SUSPENDED, we wouldn't have gotten a valid response from the org_root check
			                       'AccountStatus': 'ACTIVE'})
			return (child_accounts)
		else:
			logging.warning(f"Account {self.acct_num()} suffered a crisis of identity")
			return ()