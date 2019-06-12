import os
import traceback
from time import time, gmtime, strftime
from datetime import date
from commands import getstatusoutput, getoutput
from shutil import copy2

from PilotErrors import PilotErrors
from pUtil import tolog, readpar, timeStamp, getBatchSystemJobID, getCPUmodel, PFCxml, updateMetadata, addSkippedToPFC,\
    makeHTTPUpdate, tailPilotErrorDiag, isLogfileCopied, updateJobState, updateXMLWithSURLs, getMetadata, toPandaLogger,\
    getSiteInformation, getExperiment, readStringFromFile, merge_dictionaries, updateXMLWithEndpoints, isAnalysisJob
from JobState import JobState
from FileStateClient import getFilesOfState
from FileHandling import getOSTransferDictionaryFilename, getOSTransferDictionary, getHighestPriorityError

class PandaServerClient:
    """
    Client to the Panda Server
    Methods for communicating with the Panda Server
    """

    # private data members
    __errorString = "!!WARNING!!1992!! %s" # default error string
    __error = PilotErrors() # PilotErrors object
    __pilot_version_tag = ""
    __pilot_initdir = ""
    __jobSchedulerId = ""
    __pilotId = ""
    __updateServer = True
    __jobrec = False
    __pshttpurl = ""

    def __init__(self, pilot_version="", pilot_version_tag="", pilot_initdir="", jobSchedulerId=None, pilotId=None, updateServer=True, jobrec=False, pshttpurl=""):
        """ Default initialization """

        self.__pilot_version_tag = pilot_version_tag
        self.__pilot_initdir = pilot_initdir
        self.__jobSchedulerId = jobSchedulerId
        self.__pilotId = pilotId
        self.__updateServer = updateServer
        self.__jobrec = jobrec
        self.__pshttpurl = pshttpurl
        self.__pilot_version = pilot_version

    def getNodeStructureFromFile(self, workDir, jobId):
        """ get the node structure from the Job State file """

        JS = JobState()
        _node = None

        # open the job state file
        tolog("workDir: %s" % (workDir))
        tolog("jobId: %s" % (jobId))
        filename = JS.getFilename(workDir, jobId)
        tolog("filename: %s" % (filename))
        if os.path.exists(filename):
            # load the objects
            if JS.get(filename):
                # decode the job state info
                _job, _site, _node, _recoveryAttempt = JS.decode()
            else:
                tolog("JS.decode() failed to load objects")
        else:
            tolog("%s does not exist" % (filename))
        return _node

    def copyNodeStruct4NG(self, node):
        """ store the node structure for ARC """

        from pickle import dump
        try:
            _fname = "%s/panda_node_struct.pickle" % os.getcwd()
            fp = open(_fname, "w")
        except Exception, e:
            tolog("!!WARNING!!2999!! Could not store panda node structure: %s" % str(e))
        else:
            try:
                dump(node, fp)
                fp.close()
            except Exception, e:
                tolog("!!WARNING!!2999!! Could not dump panda node structure: %s" % str(e))
            else:
                tolog("Stored panda node structure at: %s" % (_fname))
                tolog("node : %s" % (str(node)))
                try:
                    copy2(_fname, self.__pilot_initdir)
                except Exception, e:
                    tolog("!!WARNING!!2999!! Could not copy panda node structure to init dir: %s" % str(e))
                else:
                    tolog("Copied panda node structure (%s) to init dir: %s" % (_fname, self.__pilot_initdir))

    def jobMetric(self, key="", value=""):
        """ Add 'key'='value' to the jobMetrics """
        # Use this method to avoid missing the separating space between key-value pairs in the job metrics

        if key != "" and value != "":
            # Add a space at the end since there might be several key values added
            jobMetric = "%s=%s " % (key, value)
        else:
            jobMetric = ""

        return jobMetric

    def getJobMetrics(self, job, site, workerNode):
        """ Return a properly formatted job metrics string """

        # style: Number of events read | Number of events written | vmPeak maximum | vmPeak average | RSS average | JEM activation
        # format: nEvents=<int> nEventsW=<int> vmPeakMax=<int> vmPeakMean=<int> RSSMean=<int> JEM=<string>
        #         hs06=<float> shutdownTime=<int> cpuFactor=<float> cpuLimit=<float> diskLimit=<float> jobStart=<int> memLimit=<int> runLimit=<float>

        # get the experiment object
        thisExperiment = getExperiment(job.experiment)

        if "HPC_HPC" in readpar('catchall'):
            if job.coreCount is None:
                job.coreCount = 0
        else:
            if job.coreCount:
                # Always use the ATHENA_PROC_NUMBER first, if set
                if os.environ.has_key('ATHENA_PROC_NUMBER'):
                    try:
                        job.coreCount = int(os.environ['ATHENA_PROC_NUMBER'])
                    except Exception, e:
                        tolog("ATHENA_PROC_NUMBER is not properly set: %s (will use existing job.coreCount value)" % (e))
            else:
                try:
                    job.coreCount = int(os.environ['ATHENA_PROC_NUMBER'])
                except:
                    tolog("env ATHENA_PROC_NUMBER is not set. corecount is not set")
        coreCount = job.coreCount
        jobMetrics = ""
        if coreCount is not None and coreCount != "NULL" and coreCount != 'null':
            jobMetrics += self.jobMetric(key="coreCount", value=coreCount)
        if job.nEvents > 0:
            jobMetrics += self.jobMetric(key="nEvents", value=job.nEvents)
        if job.nEventsW > 0:
            jobMetrics += self.jobMetric(key="nEventsW", value=job.nEventsW)

        if job.external_stageout_time:
            jobMetrics += self.jobMetric(key="ExStageoutTime", value=job.external_stageout_time)
        # hpc status
        #if job.mode:
        #    jobMetrics += self.jobMetric(key="mode", value=job.mode)
        #if job.hpcStatus:
        #    jobMetrics += self.jobMetric(key="HPCStatus", value=job.hpcStatus)
        if job.yodaJobMetrics:
            for key in job.yodaJobMetrics:
                if key == 'startTime' or key == 'endTime':
                    value = strftime("%Y-%m-%d %H:%M:%S", gmtime(job.yodaJobMetrics[key]))
                    jobMetrics += self.jobMetric(key=key, value=value)
                elif key.startswith("min") or key.startswith("max"):
                    pass
                else:
                    jobMetrics += self.jobMetric(key=key, value=job.yodaJobMetrics[key])
        #if job.HPCJobId:
        #    jobMetrics += self.jobMetric(key="HPCJobId", value=job.HPCJobId)

        # eventservice zip file
        if job.outputZipName and job.outputZipBucketID:
            jobMetrics += self.jobMetric(key="outputZipName", value=os.path.basename(job.outputZipName))
            jobMetrics += self.jobMetric(key="outputZipBucketID", value=job.outputZipBucketID)

        # report alternative stage-out in case alt SE method was used
        # (but not in job recovery mode)
        recovery_mode = False
        if job.filesAltStageOut > 0 and not recovery_mode:
            #_jobMetrics = ""
            #_jobMetrics += " filesAltStageOut=%d" % (job.filesAltStageOut)
            #_jobMetrics += " filesNormalStageOut=%d" % (job.filesNormalStageOut)
            #tolog("Could have reported: %s" % (_jobMetrics))

            # Report which output files were moved to an alternative SE
            filenames = getFilesOfState(site.workdir, job.jobId, state="alt_transferred")
            if filenames != "":
                jobMetrics += self.jobMetric(key="altTransferred", value=filenames)

        # report on which OS bucket the log was written to, if any
        if job.logBucketID != -1:
            jobMetrics += self.jobMetric(key="logBucketID", value=job.logBucketID)

        # only add the JEM bit if explicitly set to YES, otherwise assumed to be NO
        if job.JEM == "YES":
            jobMetrics += self.jobMetric(key="JEM", value=1)
            # old format: jobMetrics += " JEM=%s" % (job.JEM)

        if job.dbTime != "":
            jobMetrics += self.jobMetric(key="dbTime", value=job.dbTime)
        if job.dbData != "":
            jobMetrics += self.jobMetric(key="dbData", value=job.dbData)

        # machine and job features, max disk space used by the payload
        jobMetrics += workerNode.addToJobMetrics(job.result[0], self.__pilot_initdir, job.jobId)

        si = getSiteInformation(job.experiment)

        _jobMetrics = ""

        # report any OS transfers
        #message = self.getOSJobMetrics()
        #if message != "":
        #    _jobMetrics = self.jobMetric(key="OS", value=message)
        #    tolog("Could have added: %s to job metrics" % (_jobMetrics))

        # correct for potential initial and trailing space
        jobMetrics = jobMetrics.lstrip().rstrip()

        if jobMetrics != "":
            tolog('Job metrics=\"%s\"' % (jobMetrics))
        else:
            tolog("No job metrics (all values are zero)")

        # is jobMetrics within allowed size?
        if len(jobMetrics) > 500:
            tolog("!!WARNING!!2223!! jobMetrics out of size (%d)" % (len(jobMetrics)))

            # try to reduce the field size and remove the last entry which might be cut
            jobMetrics = jobMetrics[:500]
            jobMetrics = " ".join(jobMetrics.split(" ")[:-1])

            tolog("jobMetrics has been reduced to: %s" % (jobMetrics))

        return jobMetrics

    # deprecated
    def getOSJobMetrics(self):
        """ Generate the objectstore jobMetrics message """
        # Message format:
        # OS=<os_name_0>:<os_bucket_endpoint_0>:<os_bucket_endpoint_1>: ..
        # Example:
        # os_name = BNL_OS_0, os_bucket_name = atlas_eventservice_F0 or atlas_logs_3D (where F0 and 3D are examples of file name hashes)
        # -> OS=BNL_OS_0;atlas_eventservice_F0:atlas_logs_3D
        # (note: at least one os_bucket_endpoint will be included in a message, but not necessarily both of them and order is random)

        message = ""

        # Locate the OS transfer dictionary
        filename = getOSTransferDictionaryFilename()
        path = os.path.join(self.__pilot_initdir, filename)
        if os.path.exists(path):
            # Which OS's were used?
            os_names_dictionary = getOSTransferDictionary(path)
            if os_names_dictionary != {}:
                message = ""

                os_names = os_names_dictionary.keys()
                # Note: the should only be one os_name
                if len(os_names) > 1:
                    tolog("!!WARNING!!2345!! Can only report one ddm endpoint (will use first only): %s" % (os_names_dictionary))

                # Which buckets were written to?
                for os_name in os_names_dictionary.keys():
                    message += os_name + ";"
                    bucket_list = os_names_dictionary[os_name]
                    for os_bucket_endpoint in bucket_list:
                        message += os_bucket_endpoint + ":"
                        # Remove the last ':'
                        message = message[:-1]

                    # Ignore any other os_names - there should one be one and we can only report one
                    break
            else:
                tolog("!!WARNING!!3335!! No OS transfers were found in: %s" % (filename))

        else:
            tolog("OS transfer dictionary does not exist, will not report OS transfers in jobMetrics (%s)" % (path))

        return message

    def getNodeStructure(self, job, site, workerNode, spaceReport=False, log=None):
        """ define the node structure expected by the server """

        node = {}

        node['node'] = workerNode.nodename
        node['workdir'] = job.workdir
        node['siteName'] = site.sitename
        node['jobId'] = job.jobId
        node['state'] = job.result[0]
        node['timestamp'] = timeStamp()
        if job.attemptNr > -1:
            node['attemptNr'] = job.attemptNr
        if self.__jobSchedulerId:
            node['schedulerID'] = self.__jobSchedulerId
        if self.__pilotId:
            use_newmover = str(readpar('use_newmover')).lower() in ["1", "true"]
            use_newmover_tag = 'NEWMOVER-%s' % ('ON' if use_newmover else 'OFF')
            tolog("Checking if new site movers workflow is enabled: use_newmover=%s" % use_newmover)

            # report the batch system job id, if available
            batchSystemType, _id = getBatchSystemJobID()

            if batchSystemType:
                tolog("Batch system: %s" % batchSystemType)
                tolog("Batch system job ID: %s" % _id)
                node['pilotID'] = "%s|%s|%s|%s|%s" % (self.__pilotId, use_newmover_tag, batchSystemType, self.__pilot_version_tag, self.__pilot_version)
                node['batchID'] = _id
                tolog("Will send batchID: %s and pilotID: %s" % (node['batchID'], node['pilotID']))
            else:
                tolog("Batch system type was not identified (will not be reported)")
                node['pilotID'] = "%s|%s|%s|%s" % (self.__pilotId, use_newmover_tag, self.__pilot_version_tag, self.__pilot_version)
                tolog("Will send pilotID: %s" % node['pilotID'])

            tolog("pilotId: %s" % str(self.__pilotId))
        if log and (job.result[0] == 'failed' or job.result[0] == 'holding' or "outbound connections" in log):
            node['pilotLog'] = log

        # add the startTime if the file exists
        _filename = 'START_TIME_%s' % (job.jobId)
        _path = os.path.join(self.__pilot_initdir, _filename)
        if os.path.exists(_path):
            startTime = readStringFromFile(_path)
            node['startTime'] = startTime

        if job.yodaJobMetrics:
            if 'startTime' in job.yodaJobMetrics and job.yodaJobMetrics['startTime']:
                node['startTime'] = strftime("%Y-%m-%d %H:%M:%S", gmtime(job.yodaJobMetrics['startTime']))
                #job.yodaJobMetrics['startTime'] = node['startTime']
            if 'endTime' in job.yodaJobMetrics and job.yodaJobMetrics['endTime']:
                node['endTime'] = strftime("%Y-%m-%d %H:%M:%S", gmtime(job.yodaJobMetrics['endTime']))
                #job.yodaJobMetrics['endTime'] = node['endTime']

        # build the jobMetrics
        node['jobMetrics'] = self.getJobMetrics(job, site, workerNode)

        # corrupted files
        if job.corruptedFiles:
            node['corruptedFiles'] = job.corruptedFiles

        # for hpc status
        if job.hpcStatus:
            node['jobSubStatus'] = job.hpcStatus
        tolog("jobSubStatus: %s" % job.subStatus)
        if job.subStatus:
            node['jobSubStatus'] = job.subStatus

        if job.coreCount and job.coreCount != 'null' and job.coreCount != 'NULL':
            node['coreCount'] = job.coreCount
        if job.HPCJobId:
            node['batchID'] = job.HPCJobId

        # check to see if there were any high priority errors reported
        errorInfo = getHighestPriorityError(job.jobId, self.__pilot_initdir)
        if errorInfo != {}:
            try:
                pilotErrorCode = errorInfo['pilotErrorCode']
                pilotErrorDiag = errorInfo['pilotErrorDiag']
            except Exception, e:
                tolog("!!WARNING!!2323!! Exception caught: %s" % (e))
            else:
                # Overwrite any existing errors
                if pilotErrorCode == 0 and job.result[2] != 0:
                    tolog('Encountered bad high priority error code %d (will not overwrite error code %d)' % (pilotErrorCode, job.result[2]))
                else:
                    if job.result[2] != 0:
                        tolog("Encountered high priority error code %d (will overwrite error code %d)" % (pilotErrorCode, job.result[2]))
                    else:
                        tolog("Encountered high priority error code %d" % (pilotErrorCode))
                    job.result[2] = pilotErrorCode
                    job.pilotErrorDiag = pilotErrorDiag
        else:
            tolog("Did not find any reported high priority errors")

        # send pilotErrorDiag for finished, failed and holding jobs
        if job.result[0] == 'finished' or job.result[0] == 'failed' or job.result[0] == 'holding':
            # get the pilot error diag from the right source
            if job.pilotErrorDiag:
                if job.pilotErrorDiag == "":
                    node['pilotErrorDiag'] = tailPilotErrorDiag(self.__error.getPilotErrorDiag(job.result[2]))
                    job.pilotErrorDiag = node['pilotErrorDiag']
                    tolog("Empty pilotErrorDiag set to: %s" % (job.pilotErrorDiag))
                elif job.pilotErrorDiag.upper().find("<HTML>") >= 0:
                    tolog("Found html in pilotErrorDiag: %s" % (job.pilotErrorDiag))
                    node['pilotErrorDiag'] = self.__error.getPilotErrorDiag(job.result[2])
                    job.pilotErrorDiag = node['pilotErrorDiag']
                    tolog("Updated pilotErrorDiag: %s" % (job.pilotErrorDiag))
                else:
                    # truncate if necesary
                    if len(job.pilotErrorDiag) > 250:
                        tolog("pilotErrorDiag will be truncated to size 250")
                        tolog("Original pilotErrorDiag message: %s" % (job.pilotErrorDiag))
                        job.pilotErrorDiag = job.pilotErrorDiag[:250]
                    # set the pilotErrorDiag, but only the last 256 characters
                    node['pilotErrorDiag'] = tailPilotErrorDiag(job.pilotErrorDiag)
            else:
                # set the pilotErrorDiag, but only the last 256 characters
                job.pilotErrorDiag = self.__error.getPilotErrorDiag(job.result[2])
                node['pilotErrorDiag'] = tailPilotErrorDiag(job.pilotErrorDiag)
                tolog("Updated pilotErrorDiag from None: %s" % (job.pilotErrorDiag))

        # get the number of events, should report in heartbeat in case of preempted.
        if job.nEvents != 0:
            node['nEvents'] = job.nEvents
            tolog("Total number of processed events: %d (read)" % (job.nEvents))
        else:
            tolog("Payload/TRF did not report the number of read events")

        try:
            # report CPUTime and CPUunit at the end of the job
            try:
                constime = int(job.cpuConsumptionTime)
            except:
                constime = None
            if constime:
                if constime < 10**9:
                    node['cpuConsumptionTime'] = job.cpuConsumptionTime
                else:
                    tolog("!!WARNING!!2222!! Unrealistic cpuConsumptionTime: %s (reset to -1)" % job.cpuConsumptionTime)
                    node['cpuConsumptionTime'] = "-1"
        except:
            tolog("Failed to get cpu time: %s" % traceback.format_exc())

        try:
            node['cpuConsumptionUnit'] = job.cpuConsumptionUnit + "+" + getCPUmodel()
        except:
            node['cpuConsumptionUnit'] = '?'
        node['cpuConversionFactor'] = job.cpuConversionFactor

        if job.result[0] == 'finished' or job.result[0] == 'failed':
            # make sure there is no mismatch between the transformation error codes (when both are reported)
            # send transformation errors depending on what is available
            if job.exeErrorDiag != "":
                node['exeErrorCode'] = job.exeErrorCode
                node['exeErrorDiag'] = job.exeErrorDiag

                # verify that exeErrorCode is set, if not, use the info in result[1]
                if job.exeErrorCode == 0:
                    tolog("WARNING: job.exeErrorDiag is set but not job.exeErrorCode: setting it to: %d" % (job.result[1]))
                    job.exeErrorCode = job.result[1]
                    node['exeErrorCode'] = job.exeErrorCode
            else:
                node['transExitCode'] = job.result[1]
            if (job.result[0] == 'failed') and (job.exeErrorCode != 0) and (job.result[1] != job.exeErrorCode):
                if log:
                    mismatch = "MISMATCH | Trf error code mismatch: exeErrorCode = %d, transExitCode = %d" %\
                               (job.exeErrorCode, job.result[1])
                    if node.has_key('pilotLog'):
                        node['pilotLog'] = mismatch + node['pilotLog']
                    else:
                        tolog("!!WARNING!!1300!! Could not write mismatch error to log extracts: %s" % mismatch)

            # check if Pilot-controlled resubmission is required:
            analyJob = isAnalysisJob(job.trf.split(",")[0])
            if (job.result[0] == "failed" and analyJob):
                pilotExitCode = job.result[2]
                error = PilotErrors()
                if (error.isPilotResubmissionErrorCode(pilotExitCode) or job.isPilotResubmissionRequired):
                    # negate PilotError, ensure it's negative
                    job.result[2] = -abs(pilotExitCode)
                    tolog("(Negated error code)")
                else:
                    tolog("(No need to negate error code)")

            node['pilotErrorCode'] = job.result[2]
            tolog("Pilot error code: %d" % (node['pilotErrorCode']))

            # report specific time measures
            # node['pilotTiming'] = "getJob=%s setup=%s stageIn=%s payload=%s stageOut=%s" % (job.timeGetJob, job.timeSetup, job.timeStageIn, job.timeExe, job.timeStageOut)
            node['pilotTiming'] = "%s|%s|%s|%s|%s" % (job.timeGetJob, job.timeStageIn, job.timeExe, job.timeStageOut, job.timeSetup)

        elif job.result[0] == 'holding':
            node['exeErrorCode'] = job.result[2]
            node['exeErrorDiag'] = self.__error.getPilotErrorDiag(job.result[2])

        else:
            node['cpuConsumptionUnit'] = getCPUmodel()

        # Add the utility info if it is available
        thisExperiment = getExperiment(job.experiment)
        if thisExperiment.shouldExecuteUtility():
            utility_node = thisExperiment.getUtilityInfo(job.workdir, self.__pilot_initdir, allowTxtFile=True)
            node = merge_dictionaries(node, utility_node)

        return node

    def getXML(self, job, sitename, workdir, xmlstr=None, jr=False):
        """ Get the metadata xml """

        node_xml = ""
        tolog("getXML called")

        # for backwards compatibility
        try:
            experiment = job.experiment
        except:
            experiment = "unknown"

        # do not send xml for state 'holding' (will be sent by a later pilot during job recovery)
        if job.result[0] == 'holding' and sitename != "CERNVM":
            pass
        else:
            # only create and send log xml if the log was transferred
            if job.result[0] == 'failed' and isLogfileCopied(workdir, job.jobId):
                # generate the xml string for log file
                # at this time the job.workdir might have been removed (because this function can be called
                # after the removal of workdir is done), so we make a new dir
                xmldir = "%s/XML4PandaJob_%s" % (workdir, job.jobId)
                # group rw permission added as requested by LYON
                ec, rv = getstatusoutput("mkdir -m g+rw %s" % (xmldir))
                if ec != 0:
                    tolog("!!WARNING!!1300!! Could not create xmldir from updatePandaServer: %d, %s (resetting to site workdir)" % (ec, rv))
                    cmd = "ls -l %s" % (xmldir)
                    out = getoutput(cmd)
                    tolog("%s \n%s" % (cmd, out))
                    xmldir = workdir

                if os.environ.has_key('Nordugrid_pilot'):
                    fname = os.path.join(self.__pilot_initdir, job.logFile)
                else:
                    fname = os.path.join(workdir, job.logFile)
                if os.path.exists(fname):
                    fnamelog = "%s/logfile.xml" % (xmldir)
                    guids_status = PFCxml(experiment, fnamelog, fntag="lfn", alog=job.logFile, alogguid=job.tarFileGuid, jr=jr, logToOS=job.putLogToOS)
                    from SiteMover import SiteMover
                    ec, pilotErrorDiag, _fsize, _checksum = SiteMover.getLocalFileInfo(fname, csumtype="adler32")
                    if ec != 0:
                        tolog("!!WARNING!!1300!! getLocalFileInfo failed: (%d, %s, %s)" % (ec, str(_fsize), str(_checksum)))
                        tolog("!!WARNING!!1300!! Can not set XML (will not be sent to server)")
                        node_xml = ''
                    else:
                        ec, _strXML = updateMetadata(fnamelog, _fsize, _checksum)
                        if ec == 0:
                            tolog("Added (%s, %s) to metadata file (%s)" % (_fsize, _checksum, fnamelog))
                        else:
                            tolog("!!WARNING!!1300!! Could not add (%s, %s) to metadata file (%s). XML will be incomplete: %d" %\
                                  (_fsize, _checksum, fnamelog, ec))

                        # add skipped file info
                        _skippedfname = os.path.join(workdir, "skipped.xml")
                        if os.path.exists(_skippedfname):
                            ec = addSkippedToPFC(fnamelog, _skippedfname)

                        try:
                            f = open(fnamelog)
                        except Exception,e:
                            tolog("!!WARNING!!1300!! Exception caught: Can not open the file %s: %s (will not send XML)" %\
                                  (fnamelog, str(e)))
                            node_xml = ''
                        else:
                            node_xml = ''
                            for line in f:
                                node_xml += line
                            f.close()

                            # transfer logfile.xml to pilot init dir for Nordugrid
                            if os.environ.has_key('Nordugrid_pilot'):
                                try:
                                    copy2(fnamelog, self.__pilot_initdir)
                                except Exception, e:
                                    tolog("!!WARNING!!1600!! Exception caught: Could not copy NG log metadata file to init dir: %s" % str(e))
                                else:
                                    tolog("Successfully copied NG log metadata file to pilot init dir: %s" % (self.__pilot_initdir))

                else: # log file does not exist anymore
                    if isLogfileCopied(workdir, job.jobId):
                        tolog("Log file has already been copied and removed")
                        if not os.environ.has_key('Nordugrid_pilot'):
                            # only send xml with log info if the log has been transferred
                            if xmlstr:
                                node_xml = xmlstr
                                tolog("Found xml anyway (stored since before)")
                            else:
                                node_xml = ''
                                tolog("!!WARNING!!1300!! XML not found, nothing to send to server")
                    else:
                        tolog("!!WARNING!!1300!! File %s does not exist and transfer lockfile not found (job from old pilot?)" % (fname))
                        node_xml = ''

            elif xmlstr:
                # xmlstr was set in postJobTask for all files
                tolog("XML string set")

                _skippedfname = os.path.join(workdir, "skipped.xml")
                fname = "%s/metadata-%s.xml" % (workdir, job.jobId)
                if os.path.exists(fname):
                    if os.path.exists(_skippedfname):
                        # add the skipped file info if needed
                        ec = addSkippedToPFC(fname, _skippedfname)

                    # transfer metadata to pilot init dir for Nordugrid
                    if os.environ.has_key('Nordugrid_pilot'):
                        try:
                            copy2(fname, self.__pilot_initdir)
                        except Exception, e:
                            tolog("!!WARNING!!1600!! Exception caught: Could not copy metadata file to init dir for NG: %s" % str(e))
                        else:
                            tolog("Successfully copied metadata file to pilot init dir for NG: %s" % (self.__pilot_initdir))
                else:
                    tolog("Warning: Metadata does not exist: %s" % (fname))

                tolog("Will send XML")
                node_xml = xmlstr

            # we don't need the job's log file anymore, delete it (except for NG)
            if (job.result[0] == 'failed' or job.result[0] == 'finished') and not os.environ.has_key('Nordugrid_pilot'):
                try:
                    os.system("rm -rf %s/%s" % (workdir, job.logFile))
                except OSError:
                    tolog("!!WARNING!!1300!! Could not remove %s" % (job.logFile))
                else:
                    tolog("Removed log file")

        return node_xml

    def updateOutputFilesXMLWithSURLs4NG(self, experiment, siteWorkdir, jobId, outputFilesXML):
        """ Update the OutputFiles.xml file with SURLs """

        status = False

        # open and read back the OutputFiles.xml file
        _filename = os.path.join(siteWorkdir, outputFilesXML)
        if os.path.exists(_filename):
            try:
                f = open(_filename, "r")
            except Exception, e:
                tolog("!!WARNING!!1990!! Could not open file %s: %s" % (_filename, e))
            else:
                # get the metadata
                xmlIN = f.read()
                f.close()

                # update the XML
                xmlOUT = updateXMLWithSURLs(experiment, xmlIN, siteWorkdir, jobId, self.__jobrec, format='NG')

                # write the XML
                try:
                    f = open(_filename, "w")
                except OSError, e:
                    tolog("!!WARNING!!1990!! Could not open file %s: %s" % (_filename, e))
                else:
                    # write the XML and close the file
                    f.write(xmlOUT)
                    f.close()

                    tolog("Final XML for Nordugrid / CERNVM:\n%s" % (xmlOUT))
                    status = True
        else:
            tolog("!!WARNING!!1888!! Metadata file does not exist: %s" % (_filename))

        return status

    def getDateDirs(self):
        """ Return a directory path based on the current date """
        # E.g. 2014/09/22

        year = date.today().strftime("%Y")
        month = date.today().strftime("%m")
        day = date.today().strftime("%d")

        return "%s-%s-%s" % (year, month, day)

    def tryint(self, x):
        """ Used by numbered string comparison (to protect against unexpected letters in version number) """

        try:
            return int(x)
        except ValueError:
            return x

    def splittedname(self, s):
        """ Used by numbered string comparison """

        # Can also be used for sorting:
        # > names = ['YT4.11', '4.3', 'YT4.2', '4.10', 'PT2.19', 'PT2.9']
        # > sorted(names, key=splittedname)
        # ['4.3', '4.10', 'PT2.9', 'PT2.19', 'YT4.2', 'YT4.11']

        from re import split
        return tuple(self.tryint(x) for x in split('([0-9]+)', s))

    def isAGreaterOrEqualToB(self, A, B):
        """ Is numbered string A > B? """
        # > a="1.2.3"
        # > b="2.2.2"
        # > e.isAGreaterThanB(a,b)
        # False

        return self.splittedname(A) >= self.splittedname(B)

    def getPayloadMetadataFilename(self, workdir, jobId, altloc=""):
        """ Return a proper path for the payload metadata """

        filenamePayloadMetadata = ""

        # Primarily use the jobReport.json if its' version is >= 1.0.0
        _filename = os.path.join(workdir, "jobReport.json")
        if not os.path.exists(_filename) and altloc != "":
            _filename = os.path.join(altloc, "jobReport.json")
            tolog("Trying alternative location: %s" % (_filename))

        if os.path.exists(_filename):
            # Now check the version
            try:
                f = open(_filename, 'r')
            except Exception, e:
                tolog("!!WARNING!!2233!! Could not open %s: %s" % (_filename, e))
            else:
                # Now verify that the version is at least 1.0.0
                from json import load
                try:
                    jobReport_dict = load(f)
                    version = jobReport_dict['reportVersion']
                except Exception, e:
                    filenamePayloadMetadata = "%s/metadata-%s.xml.PAYLOAD" % (workdir, jobId)
                    tolog("reportVersion not found in jobReport, using default metadata XML file")
                else:
                    v = '1.0.0'
                    if self.isAGreaterOrEqualToB(version, v):
                        tolog("Will send metadata file %s since version %s is >= %s" % (_filename, version, v))
                        filenamePayloadMetadata = _filename
                    else:
                        filenamePayloadMetadata = "%s/metadata-%s.xml.PAYLOAD" % (workdir, jobId)
                        tolog('Metadata version in file %s is too old (%s < %s), will send old XML file %s' % \
                                  (os.path.basename(_filename), version, v, os.path.basename(filenamePayloadMetadata)))
        else:
            # Use default metadata file
            tolog("Did not find %s" % (_filename))
            filenamePayloadMetadata = "%s/metadata-%s.xml.PAYLOAD" % (workdir, jobId)

        # Make sure the metadata file actually exists
        if os.path.exists(filenamePayloadMetadata):
            tolog("Verified existance of metadata file: %s" % (filenamePayloadMetadata))
        else:
            tolog("WARNING: metadata file does not exist: %s" % (filenamePayloadMetadata))
            tolog("Looking for it in the pilot init dir..")
            fname = os.path.basename(filenamePayloadMetadata)
            path = os.path.join(self.__pilot_initdir, fname)
            if os.path.exists(path):
                filenamePayloadMetadata = path
                tolog("Verified existance of metadata file: %s" % (filenamePayloadMetadata))

        return filenamePayloadMetadata

    def updatePandaServer(self, job, site, workerNode, port, xmlstr=None, spaceReport=False, log=None, ra=0, jr=False, useCoPilot=False, stdout_tail="", stdout_path="", additionalMetadata=None):
        """
        Update the job status with the jobdispatcher web server.
        State is a tuple of (jobId, ["jobstatus", transExitCode, pilotErrorCode], timestamp)
        log = log extracts
        xmlstr is set in postJobTask for finished jobs (all files). Failed jobs will only send xml for log (created in this function)
        jr = job recovery mode
        """

        tolog("Updating job status in updatePandaServer(): PandaId=%s, result=%s, time=%s" % (job.getState()))

        # set any holding job to failed for sites that do not use job recovery (e.g. sites with LSF, that immediately
        # removes any work directory after the LSF job finishes which of course makes job recovery impossible)
        if not self.__jobrec:
            if job.result[0] == 'holding' and site.sitename != "CERNVM":
                job.result[0] = 'failed'
                tolog("This site does not support job recovery: HOLDING state reset to FAILED")

        # note: any changed job state above will be lost for fake server updates, does it matter?

        # get the node structure expected by the server
        node = self.getNodeStructure(job, site, workerNode, spaceReport=spaceReport, log=log)

        # skip the server update (e.g. on NG)
        if not self.__updateServer:
            tolog("(fake server update)")
            return 0, node

        # get the xml
        node['xml'] = self.getXML(job, site.sitename, site.workdir, xmlstr=xmlstr, jr=jr)

        # stdout tail in case job.debug == 'true'
        if job.debug and type(stdout_tail) is str and len(stdout_tail) > 0:
        #if job.debug and stdout_tail and stdout_tail != "":
            # protection for potentially large tails
            stdout_tail = stdout_tail[-2048:]
            node['stdout'] = stdout_tail
            tolog("Will send stdout tail:\n%s (length = %d)" % (stdout_tail, len(stdout_tail)))

            # also send the full stdout to a text indexer if required
            if stdout_path != "":
                if "stdout_to_text_indexer" in readpar('catchall') and os.path.exists(stdout_path):
                    tolog("Will send payload stdout to text indexer")

                    # get the user name, which we will use to create a proper filename
                    from SiteMover import SiteMover
                    s = SiteMover()
                    username = s.extractUsername(job.prodUserID)

                    # get setup path for xrdcp
                    try:
                        si = getSiteInformation(job.experiment)
                        setup_path = si.getLocalROOTSetup()

                        filename = "PanDA_payload_stdout-%s.txt" % (job.jobId)
                        dateDirs = self.getDateDirs()
                        remotePath = os.path.join(os.path.join(username, dateDirs), filename)
                        url = "root://faxbox.mwt2.org//group/logs/pilot/%s" % (remotePath)
                        cmd = "%sxrdcp -f %s %s" % (setup_path, stdout_path, url)
                        tolog("Executing command: %s" % (cmd))
                        rc, rs = getstatusoutput(cmd)
                        tolog("rc=%d, rs=%s" % (rc, rs))
                    except Exception, e:
                        tolog("!!WARNING!!3322!! Failed with text indexer: %s" % (e))
            else:
                tolog("stdout_path not set")
        else:
            if not job.debug:
                tolog("Stdout tail will not be sent (debug=False)")
            elif stdout_tail == "":
                tolog("Stdout tail will not be sent (no stdout tail)")
            else:
                tolog("Stdout tail will not be sent (debug=%s, stdout_tail=\'%s\')" % (str(job.debug), stdout_tail))

        # PN fake lostheartbeat
        #    if job.result[0] == "finished":
        #        node['state'] = "holding"
        #        node['xml'] = ""

        # read back node['xml'] from jobState file for CERNVM
        sendXML = True
        if site.sitename == "CERNVM":
            _node = self.getNodeStructureFromFile(site.workdir, job.jobId)
            if _node:
                if _node.has_key('xml'):
                    if _node['xml'] != "":
                        node['xml'] = _node['xml']
                        tolog("Read back metadata xml from job state file (length: %d)" % len(node['xml']))
                    else:
                        tolog("No metadata xml present in current job state file (1 - pilot should not send xml at this time)")
                        sendXML = False
                else:
                    tolog("No xml key in node structure")
                    sendXML = False
            else:
                tolog("No metadata xml present in current job state file (2 - pilot should not send xml at this time)")
                sendXML = False

            # change the state to holding for initial CERNVM job
            if not sendXML and (job.result[0] == "finished" or job.result[0] == "failed"):
                # only set the holding state if the Co-Pilot is used
                if useCoPilot:
                    job.result[0] = "holding"
                    node['state'] = "holding"

        # update job state file
        _retjs = updateJobState(job, site, node, recoveryAttempt=ra)

        # is it the final update?
        if job.result[0] == 'finished' or job.result[0] == 'failed' or job.result[0] == 'holding':
            final = True
        else:
            final = False

        # send the original xml/json if it exists (end of production job, ignore for event service job)
        filenamePayloadMetadata = self.getPayloadMetadataFilename(site.workdir, job.jobId, altloc=job.workdir)
        payloadXMLProblem = False

        # backward compatibility
        try:
            eventService = job.eventService
        except:
            eventService = False

        if os.path.exists(filenamePayloadMetadata) and final:

            # get the metadata created by the payload
            payloadXML = getMetadata(site.workdir, job.jobId, athena=True, altpath=filenamePayloadMetadata)

            # add the metadata to the node
            if payloadXML != "" and payloadXML != None:
                tolog("Adding payload metadata of size %d to node dictionary (\'metaData\' field):\n%s" % (len(payloadXML), payloadXML))
                node['metaData'] = payloadXML
            else:
                pilotErrorDiag = "Empty Athena metadata in file: %s" % (filenamePayloadMetadata)
                payloadXMLProblem = True
        else:
            # athena XML should exist at the end of the job
            analyJob = isAnalysisJob(job.trf.split(",")[0])
            if job.result[0] == 'finished' and 'Install' not in site.sitename and not analyJob and 'DDM' not in site.sitename and 'test' not in site.sitename and job.prodSourceLabel != "install" and not eventService:
                pilotErrorDiag = "Metadata does not exist: %s" % (filenamePayloadMetadata)
                payloadXMLProblem = True

        # fail the job if there was a problem with the athena metadata
        # remove the comments below if a certain trf and release should be excluded from sending metadata
        # trf_exclusions = ['merge_trf.py']
        # release_exclusions = ['14.5.2.4']
        # jobAtlasRelease = getAtlasRelease(job.release)
        # if payloadXMLProblem and job.trf.split(",")[-1] not in trf_exclusions and jobAtlasRelease[-1] not in release_exclusions:
        if payloadXMLProblem:
            if job.trf == 'Archive_tf.py' or job.trf == 'Dummy_tf.py':
                tolog("Metadata does not exist because the job is an archive/dummy job")
            else:
                tolog("!!FAILED!!1300!! %s" % (pilotErrorDiag))
                job.result[0] = "failed"
                job.result[2] = self.__error.ERR_NOPAYLOADMETADATA
                if node.has_key('pilotLog'):
                    node['pilotLog'] += "!!FAILED!!1300!! %s" % (pilotErrorDiag)
                else:
                    node['pilotLog'] = "!!FAILED!!1300!! %s" % (pilotErrorDiag)
                node['pilotErrorCode'] = job.result[2]
                node['state'] = job.result[0]

        # for backward compatibility
        try:
            experiment = job.experiment
        except:
            experiment = "unknown"

        # do not make the update if Nordugrid (leave for ARC to do)
        if os.environ.has_key('Nordugrid_pilot'):
            if final:
                # update xml with SURLs stored in special SURL dictionary file
                if self.updateOutputFilesXMLWithSURLs4NG(experiment, site.workdir, job.jobId, job.outputFilesXML):
                    tolog("Successfully added SURLs to %s" % (job.outputFilesXML))

                # update xml with SURLs stored in special SURL dictionary file
                if node.has_key('xml'):
                    tolog("Updating node structure XML with SURLs")
                    node['xml'] = updateXMLWithSURLs(experiment, node['xml'], site.workdir, job.jobId, self.__jobrec) # do not use format 'NG' here

                    # was the log file transferred to an OS? check in the OS transfer dictionary
                    tolog("job.logBucketID: %s" % job.logBucketID)
                    if job.logBucketID != -1:
                        # get the corresponding ddm endpoint
                        si = getSiteInformation(experiment)
                        os_ddmendpoint = si.getObjectstoreDDMEndpointFromBucketID(job.logBucketID)
                        node['xml'] = updateXMLWithEndpoints(node['xml'], [job.logFile], [os_ddmendpoint])
                    else:
                        node['xml'] = updateXMLWithEndpoints(node['xml'], [job.logFile], [None])

                    tolog("Updated XML:\n%s" % (node['xml']))
                else:
                    tolog("WARNING: Found no xml entry in the node structure")

                # store final node structure in pilot_initdir (will be sent to server by ARC control tower)
                self.copyNodeStruct4NG(node)
                tolog("Leaving the final update for the control tower")
            return 0, node

        # do not send xml if there was a put error during the log transfer
        _xml = None
        if final and node.has_key('xml'):
            # is the call to updateXMLWithSURLs() useless? already done in JobLog?

            # update xml with SURLs stored in special SURL dictionary file
            tolog("Updating node structure XML with SURLs")
            node['xml'] = updateXMLWithSURLs(experiment, node['xml'], site.workdir, job.jobId, self.__jobrec)

            # was the log file transferred to an OS? check in the OS transfer dictionary
            tolog("job.logBucketID: %s" % job.logBucketID)
            if job.logBucketID != -1:
                # get the corresponding ddm endpoint
                si = getSiteInformation(experiment)
                os_ddmendpoint = si.getObjectstoreDDMEndpointFromBucketID(job.logBucketID)
                node['xml'] = updateXMLWithEndpoints(node['xml'], [job.logFile], [os_ddmendpoint])
            else:
                node['xml'] = updateXMLWithEndpoints(node['xml'], [job.logFile], [None])

            tolog("Updated XML:\n%s" % (node['xml']))

            _xml = node['xml']
            if not isLogfileCopied(site.workdir, job.jobId):
                tolog("Pilot will not send xml about output files since log was not transferred")
                node['xml'] = ""

        # should XML be sent at this time?
        if not sendXML:
            tolog("Metadata xml will not be sent")
            if node.has_key('xml'):
                if node['xml'] != "":
                    _xml = node['xml']
                    node['xml'] = ""

        # add experiment specific metadata
        if final and additionalMetadata != None:
            tolog("Adding additionalMetadata to node")
            if 'metaData' in node:
                node['metaData'] += additionalMetadata
            else:
                node['metaData'] = additionalMetadata

        # make the PandaLogger update at the final job update
        if final:
            # do not send FAX info for overflow jobs (transferType=fax), only for failover jobs
            if job.filesWithFAX > 0 and job.transferType.lower() != "fax":
                tolog("Sending PandaLogger update")
                params = {}
                params['pid'] = job.jobId
                params['line'] = 0 # this is mandatory part of API, has to be present
                params['type'] = 'FAXrecovery'
                params['message'] = '"WithFAX":' + str(job.filesWithFAX) +\
                                    ',"WithoutFAX":' + str(job.filesWithoutFAX) +\
                                    ',"bytesWithFAX":' + str(job.bytesWithFAX) +\
                                    ',"bytesWithoutFAX":' + str(job.bytesWithoutFAX) +\
                                    ',"timeToCopy":' + job.timeStageIn
                toPandaLogger(params)

        # make the actual update, repeatedly if necessary (for the final update)
        #ret = makeHTTPUpdate(job.result[0], node, port, url=self.__pshttpurl, path=self.__pilot_initdir)
        if job.workdir.endswith("/"):
            job.workdir = job.workdir[:-1]
        ret = makeHTTPUpdate(job.result[0], node, port, url=self.__pshttpurl, path=os.path.dirname(job.workdir))
        if not ret[2]: # data is None for a failed update attempt
            tolog("makeHTTPUpdate returned: %s" % str(ret))
            return 1, None

        tolog("ret = %s" % str(ret))
        data = ret[1]
        tolog("data = %s" % str(data))

        if data.has_key("command"):
            job.action = data['command']

        try:
            awk = data['StatusCode']
        except:
            tolog("!!WARNING!!1300!! Having problem updating job status, set the awk to 1 for now, and continue...")
            awk = "1"
        else:
            tolog("jobDispatcher acknowledged with %s" % (awk))

        # need to have a return code so subprocess knows if update goes ok or not
        ecode = int(awk) # use the awk code from jobdispatcher as the exit code

        # PN fake lostheartbeat
        #    if job.result[0] == "finished":
        #        ecode = 1

        # reset xml in case it was overwritten above for failed log transfers
        if final and node.has_key('xml'):
            node['xml'] = _xml

        # if final update, now it's safe to remove any lingering memory output files from the init dir
        if final:
            try:
                filename = os.path.join(self.__pilot_initdir, "memory_monitor*")
                tolog("Will remove any lingering %s files from the init directory" % (filename))
                os.system("rm -rf %s" % (filename))
            except Exception, e:
                tolog("!!WARNING!!4343!! Failed to remove %s: %s" % (filename), e)

        return ecode, node # ecode=0 : update OK, otherwise something wrong
