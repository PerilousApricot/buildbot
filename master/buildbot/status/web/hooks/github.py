#!/usr/bin/env python
"""
github_buildbot.py is based on git_buildbot.py

github_buildbot.py will determine the repository information from the JSON 
HTTP POST it receives from github.com and build the appropriate repository.
If your github repository is private, you must add a ssh key to the github
repository for the user who initiated the build on the buildslave.

"""

import tempfile
import logging
import re
import sys
import traceback
from twisted.web import server, resource
from twisted.internet import reactor
from twisted.spread import pb
from twisted.cred import credentials
from optparse import OptionParser
from buildbot.changes.changes import Change
import datetime
import time


try:
    import json
except ImportError:
    import simplejson as json


class GitHubBuildBot(resource.Resource):
    """
    GitHubBuildBot creates the webserver that responds to the GitHub Service
    Hook.
    """
    isLeaf = True
    master = None
    port = None
    
    def render_POST(self, request):
        """
        Reponds only to POST events and starts the build process
        
        :arguments:
            request
                the http request object
        """
        try:
            payload = json.loads(request.args['payload'][0])
            user = payload['repository']['owner']['name']
            repo = payload['repository']['name']
            repo_url = payload['repository']['url']
            self.private = payload['repository']['private']
            logging.debug("Payload: " + str(payload))
            self.process_change(payload, user, repo, repo_url)
        except Exception:
            logging.error("Encountered an exception:")
            for msg in traceback.format_exception(*sys.exc_info()):
                logging.error(msg.strip())

    def process_change(self, payload, user, repo, repo_url):
        """
        Consumes the JSON as a python object and actually starts the build.
        
        :arguments:
            payload
                Python Object that represents the JSON sent by GitHub Service
                Hook.
        """
        changes = []
        newrev = payload['after']
        refname = payload['ref']
        
        # We only care about regular heads, i.e. branches
        match = re.match(r"^refs\/heads\/(.+)$", refname)
        if not match:
            logging.info("Ignoring refname `%s': Not a branch" % refname)

        branch = match.group(1)
        # Find out if the branch was created, deleted or updated. Branches
        # being deleted aren't really interesting.
        if re.match(r"^0*$", newrev):
            logging.info("Branch `%s' deleted, ignoring" % branch)
        else: 
            for commit in payload['commits']:
                files = []
                files.extend(commit['added'])
                files.extend(commit['modified'])
                files.extend(commit['removed'])
                change = {'revision': commit['id'],
                     'revlink': commit['url'],
                     'comments': commit['message'],
                     'branch': branch,
                     'who': commit['author']['name'] 
                            + " <" + commit['author']['email'] + ">",
                     'files': files,
                     'links': [commit['url']],
                     'properties': {'repository': repo_url},
                }
                changes.append(change)
        
        # Submit the changes, if any
        if not changes:
            logging.warning("No changes found")
            return
                    
        host, port = self.master.split(':')
        port = int(port)

        factory = pb.PBClientFactory()
        deferred = factory.login(credentials.UsernamePassword("change",
                                                                "changepw"))
        reactor.connectTCP(host, port, factory)
        deferred.addErrback(self.connectFailed)
        deferred.addCallback(self.connected, changes)


    def connectFailed(self, error):
        """
        If connection is failed.  Logs the error.
        """
        logging.error("Could not connect to master: %s"
                % error.getErrorMessage())
        return error

    def addChange(self, dummy, remote, changei):
        """
        Sends changes from the commit to the buildmaster.
        """
        logging.debug("addChange %s, %s" % (repr(remote), repr(changei)))
        try:
            change = changei.next()
        except StopIteration:
            remote.broker.transport.loseConnection()
            return None
    
        logging.info("New revision: %s" % change['revision'][:8])
        for key, value in change.iteritems():
            logging.debug("  %s: %s" % (key, value))
    
        deferred = remote.callRemote('addChange', change)
        deferred.addCallback(self.addChange, remote, changei)
        return deferred

    def connected(self, remote, changes):
        """
        Reponds to the connected event.
        """
        return self.addChange(None, remote, changes.__iter__())


def getChanges(request, options = None):
        """
        Reponds only to POST events and starts the build process
        
        :arguments:
            request
                the http request object
        """
        try:
            payload = json.loads(request.args['payload'][0])
            user = payload['repository']['owner']['name']
            repo = payload['repository']['name']
            repo_url = payload['repository']['url']
            private = payload['repository']['private']
            logging.debug("Payload: " + str(payload))
            return process_change(payload, user, repo, repo_url)
        except Exception:
            logging.error("Encountered an exception:")
            for msg in traceback.format_exception(*sys.exc_info()):
                logging.error(msg.strip())

def process_change(payload, user, repo, repo_url):
        """
        Consumes the JSON as a python object and actually starts the build.
        
        :arguments:
            payload
                Python Object that represents the JSON sent by GitHub Service
                Hook.
        """
        changes = []
        newrev = payload['after']
        refname = payload['ref']
        logging.info( "in process_change" )
        # We only care about regular heads, i.e. branches
        match = re.match(r"^refs\/heads\/(.+)$", refname)
        if not match:
            logging.info("Ignoring refname `%s': Not a branch" % refname)

        branch = match.group(1)
        # Find out if the branch was created, deleted or updated. Branches
        # being deleted aren't really interesting.
#        {"removed":[],
#        "modified":["setup.py"],
#        "message":"Give some polite messages when trying to run lint/coverage without the modules being installed.",
#        "added":[],
#        "url":"http://github.com/PerilousApricot/WMCore/commit/71f79484bde30a1d2067719e13df8212c4032c2e",
#        "timestamp":"2010-01-12T05:02:37-08:00",
#        "id":"71f79484bde30a1d2067719e13df8212c4032c2e",
#        "author":{"email":"metson","name":"metson"}}

        if re.match(r"^0*$", newrev):
            logging.info("Branch `%s' deleted, ignoring" % branch)
            return []
        else: 
            for commit in payload['commits']:
                files = []
                files.extend(commit['added'])
                files.extend(commit['modified'])
                files.extend(commit['removed'])
                # you know what sucks? this. converting
                # from the github provided time to a unix timestamp
                # python2.4 doesn't have the %z argument to strptime
                # which means it won't accept a numeric timezone offset
                
                # this is time according to the local time
                when =  time.mktime(time.strptime(\
                                     (commit['timestamp'][:-6]),\
                                    "%Y-%m-%dT%H:%M:%S"))
                # shift the time according to the offset
                hourShift    = commit['timestamp'][-5:-4]
                minShift     = commit['timestamp'][-2:-1]
                totalSeconds = hourShift * 60 * 60 + minShift *60
                
                logging.info("TZ adjust .. hour: %s min: %s total: %s" % (hourShift, minShift, totalSeconds))                
                if commit['timestamp'][-6] == '+':
                    # we need to go left to get back to UTC
                    when -= totalSeconds
                elif commit['timestamp'][-6] == '-':
                    when += totalSeconds
                else:
                    raise RuntimeError, "Unknown timestamp from github"
                
                change = {'revision': commit['id'],
                     'revlink': commit['url'],
                     'comments': commit['message'],
                     'branch': branch,
                     'who': commit['author']['name'] 
                            + " <" + commit['author']['email'] + ">",
                     'files': files,
                     'links': [commit['url']],
                     'properties': {'repository': repo_url},
                }
    
                logging.info("New revision: %s" % change['revision'][:8])
                for key, value in change.iteritems():
                    logging.debug("  %s: %s" % (key, value))
                changeObject = Change(\
                        who      = commit['author']['name'] 
                                    + " <" + commit['author']['email'] + ">",
                        files    = files,
                        comments = commit['message'], 
                        links    = [commit['url']],
                        revision = commit['id'],
                        # github gives this
                        # "2010-07-23T11:47:57-07:00"
                        # rowdy, but we need to strip the last colon
                        # to inport to strptime
                        when     = when,
                        branch   = branch,
                        revlink  = commit['url'], 
                        repository = repo_url)  
                changes.append(changeObject) 
            return changes
        