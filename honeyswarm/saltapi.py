import os
from pepper.libpepper import Pepper
from pepper.exceptions import PepperException
# https://docs.saltstack.com/en/latest/ref/clients/#python-client-api


class PepperApi():
    def __init__(self):
        self.authenticated = False
        self.api = Pepper(os.environ.get("SALT_HOST"))
        self.api_auth()

    def api_auth(self):
        try:
            auth_test = self.api.login(
                os.environ.get("SALT_USERNAME"),
                os.environ.get("SALT_SHARED_SECRET"),
                'sharedsecret')
            self.authenticated = True
        except Exception as err:
            print(err)
            self.authenticated = False

    def salt_keys(self):
        """
        Queries the Salt Master for all Minion keys

        Returns:
            dict: A dictionary with 3 lists for minions,
            pre-minions and rejected minions
        """
        # check auth state
        self.api_auth()
        api_reponse = self.api.low(
            [{'client': 'wheel', 'fun': 'key.list_all'}]
            )
        if api_reponse['return'][0]['data']['success']:
            return api_reponse['return'][0]['data']['return']

    def accept_key(self, minion_id):
        """
        Tells the Salt Master to Accept a Key by its name

        Args:
            minion_id (str): Minion ID -
            should be a Mongo ID from `Hive` modal

        Returns:
            dict: A dictionary with the ID for any accepted minions.
        """
        # check auth state
        self.api_auth()
        api_reponse = self.api.low(
            [{'client': 'wheel', 'fun': 'key.accept', 'match': minion_id}]
            )
        if api_reponse['return'][0]['data']['success']:
            return api_reponse['return'][0]['data']['return']

    def delete_key(self, minion_id):
        """Given a Minion ID will delete the key from the salt master"""
        # check auth state
        self.api_auth()
        api_reponse = self.api.low(
            [{'client': 'wheel', 'fun': 'key.delete', 'match': minion_id}]
            )
        if api_reponse['return'][0]['data']['success']:
            return api_reponse['return'][0]['data']['return']

    def run_client_function_async(self, target, function):
        """
        Basic Function Runner; for things like test.ping it is up to
        the receiving function to parse the data it needs.
        Makes Async Call returns Job ID
        """
        # check auth state
        self.api_auth()
        api_reponse = self.api.low(
            [{'client': 'local_async', 'tgt': target, 'fun': function}]
            )
        return api_reponse['return'][0]['jid']

    def run_client_function(self, target, function):
        """
        Basic Function Runner; for things like test.ping it
        is up to the receiving function to parse the data it needs.
        Not async so blocking?
        """
        # check auth state
        self.api_auth()
        api_reponse = self.api.low(
            [{'client': 'local', 'tgt': target, 'fun': function}]
            )
        return api_reponse['return'][0]

    def apply_state(self, target, args_list):
        """
        Tells the Salt Master to apply a given state to a named minion

        Args:
            target (str): Minion ID - should be a Mongo ID
            from `Hive` modal
            args_list (list): List of args. First element in list MUST
            be the Salt State to apply

        Returns:
            str: Salt Job ID
        """
        # check auth state
        self.api_auth()
        api_reponse = self.api.low(
            [{
                'client':
                'local_async',
                'tgt': target,
                'fun': "state.apply",
                'arg': args_list
                }]
            )
        return api_reponse['return'][0]['jid']

    def lookup_job(self, job_id):
        """
        Query the Salt Master for a job by its Salt Job ID

        Args:
            job_id (str): Salt Job Id should be taken from PepperJobs Model

        Returns:
            dict/None: Return None if job still pending else dictionary of
            all state modules and their outputs.
        """
        # check auth state
        self.api_auth()
        try:
            api_response = self.api.lookup_jid(job_id)
            if len(api_response['return'][0]) == 0:
                return None
            else:
                return api_response['return'][0]
        except Exception as err:
            print(err)
        return None


pepper_api = PepperApi()
