# Class definition:
#   RunJob
#   This is the main RunJob class; RunJobEvent etc will inherit from this class
#   Note: at the moment, this class is essentially the old runJob module turned object oriented.
#         The class will later become RunJobNormal, ie responible for running normal PanDA jobs.
#         At that point a new RunJob top class will be created containing methods that have been
#         identified as common between the various sub classes.
#   Instances are generated with RunJobFactory
#   Subclasses should implement all needed methods prototyped in this class
#   Note: not compatible with Singleton Design Pattern due to the subclassing

# Standard python modules
import os, sys, commands, time
import traceback
import atexit, signal
from optparse import OptionParser
from json import loads

# Pilot modules
import Site, pUtil, Job, Node, RunJobUtilities
import Mover as mover
from pUtil import tolog, readpar, createLockFile, getDatasetDict, getSiteInformation,\
     tailPilotErrorDiag, getCmtconfig, getExperiment, getGUID, getWriteToInputFilenames
from JobRecovery import JobRecovery
from FileStateClient import updateFileStates, dumpFileStates
from ErrorDiagnosis import ErrorDiagnosis # import here to avoid issues seen at BU with missing module
from PilotErrors import PilotErrors
from shutil import copy2
from FileHandling import tail, getExtension, extractOutputFiles, getDestinationDBlockItems, getDirectAccess, writeFile, readFile
from EventRanges import downloadEventRanges
from processes import get_cpu_consumption_time

# remove logguid, debuglevel - not needed
# relabelled -h, queuename to -b (debuglevel not used)


class RunJob(object):

    # private data members
    __runjob = "RunJob"                  # String defining the RunJob class
    __instance = None                    # Boolean used by subclasses to become a Singleton
    __error = PilotErrors()              # PilotErrors object

#    __appdir = "/usatlas/projects/OSG"   # Default software installation directory
#    __debugLevel = 0                     # 0: debug info off, 1: display function name when called, 2: full debug info
    __failureCode = None                 # set by signal handler when user/batch system kills the job
    __globalPilotErrorDiag = ""          # global pilotErrorDiag used with signal handler (only)
    __globalErrorCode = 0                # global error code used with signal handler (only)
    __inputDir = ""                      # location of input files (source for mv site mover)
    __logguid = None                     # guid for the log file
    __outputDir = ""                     # location of output files (destination for mv site mover)
    __pilot_initdir = ""                 # location of where the pilot is untarred and started
    __pilotlogfilename = "pilotlog.txt"  # default pilotlog filename
    __pilotserver = "localhost"          # default server
    __pilotport = 88888                  # default port
    __proxycheckFlag = True              # True (default): perform proxy validity checks, False: no check
    __pworkdir = "/tmp"                  # site work dir used by the parent
#    __queuename = ""                     # PanDA queue  NOT NEEDED
#    __sitename = "testsite"              # PanDA site  NOT NEEDED
    __stageinretry = 1                   # number of stage-in tries
    __stageoutretry = 1                  # number of stage-out tries
#    __testLevel = 0                      # test suite control variable (0: no test, 1: put error, 2: ...)  NOT USED
#    __workdir = "/tmp" # NOT USED
    __cache = ""                         # Cache URL, e.g. used by LSST
    __pandaserver = ""                   # Full PanDA server url incl. port and sub dirs

    __recovery = False
    __jobStateFile = None
    __yodaNodes = None
    __yodaQueue = None

    corruptedFiles = []

    # Getter and setter methods

    def getExperiment(self):
        """ Getter for __experiment """

        return self.__experiment

    def getFailureCode(self):
        """ Getter for __failureCode """

        return self.__failureCode

    def setFailureCode(self, code):
        """ Setter for __failureCode """

        self.__failureCode = code

    def getGlobalPilotErrorDiag(self):
        """ Getter for __globalPilotErrorDiag """

        return self.__globalPilotErrorDiag

    def setGlobalPilotErrorDiag(self, pilotErrorDiag):
        """ Setter for __globalPilotErrorDiag """

        self.__globalPilotErrorDiag = pilotErrorDiag

    def getGlobalErrorCode(self):
        """ Getter for __globalErrorCode """

        return self.__globalErrorCode

    def setGlobalErrorCode(self, code):
        """ Setter for __globalErrorCode """

        self.__globalErrorCode = code

    def setCache(self, cache):
        """ Setter for __cache """

        self.__cache = cache

    def getInputDir(self):
        """ Getter for __inputDir """

        return self.__inputDir

    def setInputDir(self, inputDir):
        """ Setter for __inputDir """

        self.__inputDir = inputDir

    def getLogGUID(self):
        """ Getter for __logguid """

        return self.__logguid

    def getOutputDir(self):
        """ Getter for __outputDir """

        return self.__outputDir

    def getPilotInitDir(self):
        """ Getter for __pilot_initdir """

        return self.__pilot_initdir

    def setPilotInitDir(self, pilot_initdir):
        """ Setter for __pilot_initdir """

        self.__pilot_initdir = pilot_initdir

    def getPilotLogFilename(self):
        """ Getter for __pilotlogfilename """

        return self.__pilotlogfilename

    def getPilotServer(self):
        """ Getter for __pilotserver """

        return self.__pilotserver

    def getPilotPort(self):
        """ Getter for __pilotport """

        return self.__pilotport

    def getProxyCheckFlag(self):
        """ Getter for __proxycheckFlag """

        return self.__proxycheckFlag

    def getParentWorkDir(self):
        """ Getter for __pworkdir """

        return self.__pworkdir

    def setParentWorkDir(self, pworkdir):
        """ Setter for __pworkdir """

        self.__pworkdir = pworkdir

    def getStageInRetry(self):
        """ Getter for __stageinretry """

        return self.__stageinretry

    def getStageOutRetry(self):
        """ Getter for __stageoutretry """

        return self.__stageoutretry

    def setStageInRetry(self, stageinretry):
        """ Setter for __stageinretry """

        self.__stageinretry = stageinretry

    def getCache(self):
        """ Getter for __cache """

        return self.__cache

    def getRecovery(self):

        return self.__recovery

    def getJobStateFile(self):

        return self.__jobStateFile

    def  setLogGUID(self, logguid):
        """ Setter for __logguid """

        self.__logguid = logguid

    def getYodaNodes(self):
        try:
            if self.__yodaNodes is None:
                return None
            nodes = int(self.__yodaNodes)
            return nodes
        except:
            tolog(traceback.format_exc())
            return None

    def getYodaQueue(self):
        try:
            if self.__yodaQueue is None:
                return None
            return self.__yodaQueue
        except:
            tolog(traceback.format_exc())
            return None

    def getPanDAServer(self):
        """ Getter for __pandaserver """

        return self.__pandaserver

    def setPanDAServer(self, pandaserver):
        """ Setter for __pandaserver """

        self.__pandaserver = pandaserver

    # Required methods

    def __init__(self):
        """ Default initialization """

        # e.g. self.__errorLabel = errorLabel
        pass

    def getRunJob(self):
        """ Return a string with the module name """

        return self.__runjob

    def argumentParser(self):
        """ Argument parser for the RunJob module """

        # Return variables
        appdir = None
        queuename = None
        sitename = None
        workdir = None

        parser = OptionParser()
        parser.add_option("-a", "--appdir", dest="appdir",
                          help="The local path to the applications directory", metavar="APPDIR")
        parser.add_option("-b", "--queuename", dest="queuename",
                          help="Queue name", metavar="QUEUENAME")
        parser.add_option("-d", "--workdir", dest="workdir",
                          help="The local path to the working directory of the payload", metavar="WORKDIR")
        parser.add_option("-g", "--inputdir", dest="inputDir",
                          help="Location of input files to be transferred by the mv site mover", metavar="INPUTDIR")
        parser.add_option("-i", "--logfileguid", dest="logguid",
                          help="Log file guid", metavar="GUID")
        parser.add_option("-k", "--pilotlogfilename", dest="pilotlogfilename",
                          help="The name of the pilot log file", metavar="PILOTLOGFILENAME")
        parser.add_option("-l", "--pilotinitdir", dest="pilot_initdir",
                          help="The local path to the directory where the pilot was launched", metavar="PILOT_INITDIR")
        parser.add_option("-m", "--outputdir", dest="outputDir",
                          help="Destination of output files to be transferred by the mv site mover", metavar="OUTPUTDIR")
        parser.add_option("-o", "--parentworkdir", dest="pworkdir",
                          help="Path to the work directory of the parent process (i.e. the pilot)", metavar="PWORKDIR")
        parser.add_option("-s", "--sitename", dest="sitename",
                          help="The name of the site where the job is to be run", metavar="SITENAME")
        parser.add_option("-w", "--pilotserver", dest="pilotserver",
                          help="The URL of the pilot TCP server (localhost) WILL BE RETIRED", metavar="PILOTSERVER")
        parser.add_option("-p", "--pilotport", dest="pilotport",
                          help="Pilot TCP server port (default: 88888)", metavar="PORT")
        parser.add_option("-t", "--proxycheckflag", dest="proxycheckFlag",
                          help="True (default): perform proxy validity checks, False: no check", metavar="PROXYCHECKFLAG")
        parser.add_option("-x", "--stageinretries", dest="stageinretry",
                          help="The number of stage-in retries", metavar="STAGEINRETRY")
        #parser.add_option("-B", "--filecatalogregistration", dest="fileCatalogRegistration",
        #                  help="True (default): perform file catalog registration, False: no catalog registration", metavar="FILECATALOGREGISTRATION")
        parser.add_option("-E", "--stageoutretries", dest="stageoutretry",
                          help="The number of stage-out retries", metavar="STAGEOUTRETRY")
        parser.add_option("-F", "--experiment", dest="experiment",
                          help="Current experiment (default: ATLAS)", metavar="EXPERIMENT")
        parser.add_option("-R", "--recovery", dest="recovery",
                          help="Run in recovery mode", metavar="RECOVERY")
        parser.add_option("-S", "--jobStateFile", dest="jobStateFile",
                          help="Job State File", metavar="JOBSTATEFILE")
        parser.add_option("-N", "--yodaNodes", dest="yodaNodes",
                          help="Maximum nodes Yoda starts with", metavar="YODANODES")
        parser.add_option("-Q", "--yodaQueue", dest="yodaQueue",
                          help="The queue yoda will be send to", metavar="YODAQUEUE")
        parser.add_option("-H", "--cache", dest="cache",
                          help="Cache URL", metavar="CACHE")
        parser.add_option("-W", "--pandaserver", dest="pandaserver",
                          help="The full URL of the PanDA server (incl. port)", metavar="PANDASERVER")

        # options = {'experiment': 'ATLAS'}
        try:
            (options, args) = parser.parse_args()
        except Exception,e:
            tolog("!!WARNING!!3333!! Exception caught:" % (e))
            print options.experiment
        else:

            if options.appdir:
#                self.__appdir = options.appdir
                appdir = options.appdir
            if options.experiment:
                self.__experiment = options.experiment
            if options.logguid:
                self.__logguid = options.logguid
            if options.inputDir:
                self.__inputDir = options.inputDir
            if options.pilot_initdir:
                self.__pilot_initdir = options.pilot_initdir
            if options.pilotlogfilename:
                self.__pilotlogfilename = options.pilotlogfilename
            if options.pilotserver:
                self.__pilotserver = options.pilotserver
            if options.pandaserver:
                self.__pandaserver = options.pandaserver
            if options.proxycheckFlag:
                if options.proxycheckFlag.lower() == "false":
                    self.__proxycheckFlag = False
                else:
                    self.__proxycheckFlag = True
            else:
                self.__proxycheckFlag = True
            if options.pworkdir:
                self.__pworkdir = options.pworkdir
            if options.outputDir:
                self.__outputDir = options.outputDir
            if options.pilotport:
                try:
                    self.__pilotport = int(options.pilotport)
                except Exception, e:
                    tolog("!!WARNING!!3232!! Exception caught: %s" % (e))
# self.__queuename is not needed
            if options.queuename:
                queuename = options.queuename
            if options.sitename:
                sitename = options.sitename
            if options.stageinretry:
                try:
                    self.__stageinretry = int(options.stageinretry)
                except Exception, e:
                    tolog("!!WARNING!!3232!! Exception caught: %s" % (e))
            if options.stageoutretry:
                try:
                    self.__stageoutretry = int(options.stageoutretry)
                except Exception, e:
                    tolog("!!WARNING!!3232!! Exception caught: %s" % (e))
            if options.workdir:
                workdir = options.workdir
            if options.cache:
                self.__cache = options.cache

            self.__recovery = options.recovery
            self.__jobStateFile = options.jobStateFile
            if options.yodaNodes:
                self.__yodaNodes = options.yodaNodes
            if options.yodaQueue:
                self.__yodaQueue = options.yodaQueue

        return sitename, appdir, workdir, queuename

    def getRunJobFileName(self):
        """ Return the filename of the module """

        fullpath = sys.modules[self.__module__].__file__

        # Note: the filename above will contain both full path, and might end with .pyc, fix this
        filename = os.path.basename(fullpath)
        if filename.endswith(".pyc"):
            filename = filename[:-1] # remove the trailing 'c'

        return filename

    def allowLoopingJobKiller(self):
        """ Should the pilot search for looping jobs? """

        # The pilot has the ability to monitor the payload work directory. If there are no updated files within a certain
        # time limit, the pilot will consider the as stuck (looping) and will kill it. The looping time limits are set
        # in environment.py (see e.g. loopingLimitDefaultProd)

        return True

    def cleanup(self, job, rf=None):
        """ Cleanup function """
        # 'rf' is a list that will contain the names of the files that could be transferred
        # In case of transfer problems, all remaining files will be found and moved
        # to the data directory for later recovery.

        try:
            if int(job.result[1]) > 0 and (job.result[2] is None or job.result[2] == '' or int(job.result[2]) == 0):
                job.result[2] = PilotErrors.ERR_RUNJOBEXC
        except:
            tolog(traceback.format_exc())

        tolog("********************************************************")
        tolog(" This job ended with (trf,pilot) exit code of (%d,%d)" % (job.result[1], job.result[2]))
        tolog("********************************************************")

        # clean up the pilot wrapper modules
        pUtil.removePyModules(job.workdir)

        if os.path.isdir(job.workdir):
            os.chdir(job.workdir)

            # remove input files from the job workdir
            remFiles = job.inFiles
            for inf in remFiles:
                if inf and inf != 'NULL' and os.path.isfile("%s/%s" % (job.workdir, inf)): # non-empty string and not NULL
                    try:
                        os.remove("%s/%s" % (job.workdir, inf))
                    except Exception,e:
                        tolog("!!WARNING!!3000!! Ignore this Exception when deleting file %s: %s" % (inf, str(e)))
                        pass

            # only remove output files if status is not 'holding'
            # in which case the files should be saved for the job recovery.
            # the job itself must also have finished with a zero trf error code
            # (data will be moved to another directory to keep it out of the log file)

            # always copy the metadata-<jobId>.xml to the site work dir
            # WARNING: this metadata file might contain info about files that were not successfully moved to the SE
            # it will be regenerated by the job recovery for the cases where there are output files in the datadir

            try:
                tolog('job.workdir is %s pworkdir is %s ' % (job.workdir, self.__pworkdir))
                copy2("%s/metadata-%s.xml" % (job.workdir, job.jobId), "%s/metadata-%s.xml" % (self.__pworkdir, job.jobId))
            except Exception, e:
                tolog("Warning: Could not copy metadata-%s.xml to site work dir - ddm Adder problems will occure in case of job recovery" % (job.jobId))
                tolog('job.workdir is %s pworkdir is %s ' % (job.workdir, self.__pworkdir))
            if job.result[0] == 'holding' and job.result[1] == 0:
                try:
                    # create the data directory
                    os.makedirs(job.datadir)
                except OSError, e:
                    tolog("!!WARNING!!3000!! Could not create data directory: %s, %s" % (job.datadir, str(e)))
                else:
                    # find all remaining files in case 'rf' is not empty
                    remaining_files = []
                    moved_files_list = []
                    try:
                        if rf != None:
                            moved_files_list = RunJobUtilities.getFileNamesFromString(rf[1])
                            remaining_files = RunJobUtilities.getRemainingFiles(moved_files_list, job.outFiles)
                    except Exception, e:
                        tolog("!!WARNING!!3000!! Illegal return value from Mover: %s, %s" % (str(rf), str(e)))
                        remaining_files = job.outFiles

                    # move all remaining output files to the data directory
                    nr_moved = 0
                    for _file in remaining_files:
                        try:
                            os.system("mv %s %s" % (_file, job.datadir))
                        except OSError, e:
                            tolog("!!WARNING!!3000!! Failed to move file %s (abort all)" % (_file))
                            break
                        else:
                            nr_moved += 1

                    tolog("Moved %d/%d output file(s) to: %s" % (nr_moved, len(remaining_files), job.datadir))

                    # remove all successfully copied files from the local directory
                    nr_removed = 0
                    for _file in moved_files_list:
                        try:
                            os.system("rm %s" % (_file))
                        except OSError, e:
                            tolog("!!WARNING!!3000!! Failed to remove output file: %s, %s" % (_file, e))
                        else:
                            nr_removed += 1

                    tolog("Removed %d output file(s) from local dir" % (nr_removed))

                    # copy the PoolFileCatalog.xml for non build jobs
                    if not pUtil.isBuildJob(remaining_files):
                        _fname = os.path.join(job.workdir, "PoolFileCatalog.xml")
                        tolog("Copying %s to %s" % (_fname, job.datadir))
                        try:
                            copy2(_fname, job.datadir)
                        except Exception, e:
                            tolog("!!WARNING!!3000!! Could not copy PoolFileCatalog.xml to data dir - expect ddm Adder problems during job recovery")

            # remove all remaining output files from the work directory
            # (a successfully copied file should already have been removed by the Mover)
            rem = False
            for inf in job.outFiles:
                if inf and inf != 'NULL' and os.path.isfile("%s/%s" % (job.workdir, inf)): # non-empty string and not NULL
                    try:
                        os.remove("%s/%s" % (job.workdir, inf))
                    except Exception,e:
                        tolog("!!WARNING!!3000!! Ignore this Exception when deleting file %s: %s" % (inf, str(e)))
                        pass
                    else:
                        tolog("Lingering output file removed: %s" % (inf))
                        rem = True
            if not rem:
                tolog("All output files already removed from local dir")

        tolog("Payload cleanup has finished")

    def sysExit(self, job, rf=None):
        '''
        wrapper around sys.exit
        rs is the return string from Mover::put containing a list of files that were not transferred
        '''

        self.cleanup(job, rf=rf)
        sys.stderr.close()
        tolog("RunJob (payload wrapper) has finished")
        # change to sys.exit?
        os._exit(job.result[2]) # pilotExitCode, don't confuse this with the overall pilot exit code,
                                # which doesn't get reported back to panda server anyway

    def failJob(self, transExitCode, pilotExitCode, job, ins=None, pilotErrorDiag=None, docleanup=True):
        """ set the fail code and exit """

        if docleanup:
            self.cleanup(job, rf=None)

        if job.eventServiceMerge:
            if self.corruptedFiles:
                job.corruptedFiles = ','.join([e['lfn'] for e in self.corruptedFiles])
                job.result[2] = self.corruptedFiles[0]['status_code']
            else:
                pilotExitCode = PilotErrors.ERR_ESRECOVERABLE
        job.setState(["failed", transExitCode, pilotExitCode])
        if pilotErrorDiag:
            job.pilotErrorDiag = pilotErrorDiag
        tolog("Will now update local pilot TCP server")
        rt = RunJobUtilities.updatePilotServer(job, self.__pilotserver, self.__pilotport, final=True)
        if ins:
            ec = pUtil.removeFiles(job.workdir, ins)

        if docleanup:
            self.sysExit(job)

    def isMultiTrf(self, parameterList):
        """ Will we execute multiple jobs? """

        if len(parameterList) > 1:
            multi_trf = True
        else:
            multi_trf = False

        return multi_trf

    def setup(self, job, jobSite, thisExperiment):
        """ prepare the setup and get the run command list """

        # start setup time counter
        t0 = time.time()
        ec = 0
        runCommandList = []

        # split up the job parameters to be able to loop over the tasks
        jobParameterList = job.jobPars.split("\n")
        jobHomePackageList = job.homePackage.split("\n")
        jobTrfList = job.trf.split("\n")
        job.release = thisExperiment.formatReleaseString(job.release)
        releaseList = thisExperiment.getRelease(job.release)

        tolog("Number of transformations to process: %s" % len(jobParameterList))
        multi_trf = self.isMultiTrf(jobParameterList)

        # verify that the multi-trf job is setup properly
        ec, job.pilotErrorDiag, releaseList = RunJobUtilities.verifyMultiTrf(jobParameterList, jobHomePackageList, jobTrfList, releaseList)
        if ec > 0:
            return ec, runCommandList, job, multi_trf

        os.chdir(jobSite.workdir)
        tolog("Current job workdir is %s" % os.getcwd())

        # setup the trf(s)
        _i = 0
        _stdout = job.stdout
        _stderr = job.stderr
        _first = True
        for (_jobPars, _homepackage, _trf, _swRelease) in map(None, jobParameterList, jobHomePackageList, jobTrfList, releaseList):
            tolog("Preparing setup %d/%d" % (_i + 1, len(jobParameterList)))

            # reset variables
            job.jobPars = _jobPars
            job.homePackage = _homepackage
            job.trf = _trf
            job.release = _swRelease
            if multi_trf:
                job.stdout = _stdout.replace(".txt", "_%d.txt" % (_i + 1))
                job.stderr = _stderr.replace(".txt", "_%d.txt" % (_i + 1))

            # post process copysetup variable in case of directIn/useFileStager
            _copysetup = readpar('copysetup')
            _copysetupin = readpar('copysetupin')
            if "--directIn" in job.jobPars or "--useFileStager" in job.jobPars or _copysetup.count('^') == 5 or _copysetupin.count('^') == 5:
                # only need to update the queuedata file once
                if _first:
                    RunJobUtilities.updateCopysetups(job.jobPars)
                    _first = False

            # setup the trf
            ec, job.pilotErrorDiag, cmd, job.spsetup, job.JEM, job.cmtconfig = thisExperiment.getJobExecutionCommand(job, jobSite, self.__pilot_initdir)
            if ec > 0:
                # setup failed
                break

            # add the setup command to the command list
            runCommandList.append(cmd)
            _i += 1

        job.stdout = _stdout
        job.stderr = _stderr
        job.timeSetup = int(time.time() - t0)
        tolog("Total setup time: %d s" % (job.timeSetup))

        return ec, runCommandList, job, multi_trf


    def stageIn_new(self,
                    job,
                    jobSite,
                    analysisJob=None,  # not used: job.isAnalysisJob() should be used instead
                    files=None,
                    pfc_name="PoolFileCatalog.xml"):
        """
            Perform the stage-in
            Do transfer input files
            new site movers based implementation workflow
        """

        tolog("Preparing for get command [stageIn_new]")

        infiles = [e.lfn for e in job.inData]

        tolog("Input file(s): (%s in total)" % len(infiles))
        for ind, lfn in enumerate(infiles, 1):
            tolog("%s. %s" % (ind, lfn))

        if not infiles:
            tolog("No input files for this job .. skip stage-in")
            return job, infiles, None, False

        t0 = os.times()

        job.result[2], job.pilotErrorDiag, _dummy, FAX_dictionary = mover.get_data_new(job, jobSite, stageinTries=self.__stageinretry, proxycheck=False, workDir=self.__pworkdir, pfc_name=pfc_name, files=files)

        t1 = os.times()

        # record failed stagein files
        for e in job.inData:
            if e.status == 'error':
                failed_file = {'lfn': e.lfn, 'status': e.status, 'status_code': e.status_code, 'status_message': e.status_message}
                self.corruptedFiles.append(failed_file)

        job.timeStageIn = int(round(t1[4] - t0[4]))

        usedFAXandDirectIO = FAX_dictionary.get('usedFAXandDirectIO', False)

        statusPFCTurl = None

        return job, infiles, statusPFCTurl, usedFAXandDirectIO


    @mover.use_newmover(stageIn_new)
    def stageIn(self, job, jobSite, analysisJob, pfc_name="PoolFileCatalog.xml", prefetcher=False):
        """ Perform the stage-in """

        ec = 0
        statusPFCTurl = None
        usedFAXandDirectIO = False

        # Prepare the input files (remove non-valid names) if there are any
        ins, job.filesizeIn, job.checksumIn = RunJobUtilities.prepareInFiles(job.inFiles, job.filesizeIn, job.checksumIn)
        if ins and not prefetcher:
            tolog("Preparing for get command")

            # Get the file access info (only useCT is needed here)
            si = getSiteInformation(self.getExperiment())
            useCT, oldPrefix, newPrefix = si.getFileAccessInfo(job.transferType)

            # Transfer input files
            tin_0 = os.times()
            ec, job.pilotErrorDiag, statusPFCTurl, FAX_dictionary = \
                mover.get_data(job, jobSite, ins, self.__stageinretry, analysisJob=analysisJob, usect=useCT,\
                               pinitdir=self.__pilot_initdir, proxycheck=False, inputDir=self.__inputDir, workDir=self.__pworkdir, pfc_name=pfc_name)
            if ec != 0:
                job.result[2] = ec
            tin_1 = os.times()
            job.timeStageIn = int(round(tin_1[4] - tin_0[4]))

            # Extract any FAX info from the dictionary
            job.filesWithoutFAX = FAX_dictionary.get('N_filesWithoutFAX', 0)
            job.filesWithFAX = FAX_dictionary.get('N_filesWithFAX', 0)
            job.bytesWithoutFAX = FAX_dictionary.get('bytesWithoutFAX', 0)
            job.bytesWithFAX = FAX_dictionary.get('bytesWithFAX', 0)
            usedFAXandDirectIO = FAX_dictionary.get('usedFAXandDirectIO', False)
        elif prefetcher:
            tolog("No need to stage in files since prefetcher will be used")
        return job, ins, statusPFCTurl, usedFAXandDirectIO

    def getTrfExitInfo(self, exitCode, workdir):
        """ Get the trf exit code and info from job report if possible """

        exitAcronym = ""
        exitMsg = ""

        # does the job report exist?
        extension = getExtension(alternative='pickle')
        if extension.lower() == "json":
            _filename = "jobReport.%s" % (extension)
        else:
            _filename = "jobReportExtract.%s" % (extension)
        filename = os.path.join(workdir, _filename)

        if os.path.exists(filename):
            tolog("Found job report: %s" % (filename))

            # wait a few seconds to make sure the job report is finished
            tolog("Taking a 5s nap to make sure the job report is finished")
            time.sleep(5)

            # first backup the jobReport to the job workdir since it will be needed later
            # (the current location will disappear since it will be tarred up in the jobs' log file)
            d = os.path.join(workdir, '..')
            try:
                copy2(filename, os.path.join(d, _filename))
            except Exception, e:
                tolog("Warning: Could not backup %s to %s: %s" % (_filename, d, e))
            else:
                tolog("Backed up %s to %s" % (_filename, d))

            # search for the exit code
            try:
                f = open(filename, "r")
            except Exception, e:
                tolog("!!WARNING!!1112!! Failed to open job report: %s" % (e))
            else:
                if extension.lower() == "json":
                    from json import load
                else:
                    from pickle import load
                data = load(f)

                # extract the exit code and info
                _exitCode = self.extractDictionaryObject("exitCode", data)
                if _exitCode:
                    if _exitCode == 0 and exitCode != 0:
                        tolog("!!WARNING!!1111!! Detected inconsistency in %s: exitcode listed as 0 but original trf exit code was %d (using original error code)" %\
                              (filename, exitCode))
                    else:
                        exitCode = _exitCode
                _exitAcronym = self.extractDictionaryObject("exitAcronym", data)
                if _exitAcronym:
                    exitAcronym = _exitAcronym
                _exitMsg = self.extractDictionaryObject("exitMsg", data)
                if _exitMsg:
                    exitMsg = _exitMsg

                f.close()

                tolog("Trf exited with:")
                tolog("...exitCode=%d" % (exitCode))
                tolog("...exitAcronym=%s" % (exitAcronym))
                tolog("...exitMsg=%s" % (exitMsg))

        else:
            tolog("Job report not found: %s" % (filename))

        return exitCode, exitAcronym, exitMsg

    def extractDictionaryObject(self, obj, dictionary):
        """ Extract an object from a dictionary """

        _obj = None

        try:
            _obj = dictionary[obj]
        except Exception, e:
            tolog("Object %s not found in dictionary" % (obj))
        else:
            tolog('Extracted \"%s\"=%s from dictionary' % (obj, _obj))

        return _obj

    def getUtilitySubprocess(self, thisExperiment, cmd, pid, job):
        """ Return/execute the utility subprocess if required """

        utility_subprocess = None
        if thisExperiment.shouldExecuteUtility():
            try:
                mem_cmd = thisExperiment.getUtilityCommand(job_command=cmd, pid=pid, release=job.release, homePackage=job.homePackage, cmtconfig=job.cmtconfig, trf=job.trf, workdir=job.workdir)
                if mem_cmd != "":
                    utility_subprocess = self.getSubprocess(thisExperiment, mem_cmd)
                    if utility_subprocess:
                        try:
                            tolog("Process id of utility: %d" % (utility_subprocess.pid))
                        except Exception, e:
                            tolog("!!WARNING!!3436!! Exception caught: %s" % (e))
                else:
                    tolog("Could not launch utility since the command path does not exist")
            except Exception, e:
                tolog("!!WARNING!!5454!! Exception caught: %s" % (e))
                utility_subprocess = None
        else:
            tolog("Not required to run utility")

        return utility_subprocess

    def getBenchmarkSubprocess(self, node, coreCount, workdir, sitename):
        """ Return/execute the benchmark subprocess if required """
        # Output json: /tmp/cern-benchmark_$USER/bmk_tmp/result_profile.json

        benchmark_subprocess = None

        # run benchmark test if required by experiment site information object

        si = getSiteInformation(self.getExperiment())
        if si.shouldExecuteBenchmark():
            thisExperiment = getExperiment(self.getExperiment())
            cmd = si.getBenchmarkCommand(cloud=readpar('cloud'), cores=coreCount, workdir=workdir)
            benchmark_subprocess = self.getSubprocess(thisExperiment, cmd)

            if benchmark_subprocess:
                try:
                    tolog("Process id of benchmark suite: %d" % (benchmark_subprocess.pid))
                except Exception, e:
                    tolog("!!WARNING!!3436!! Exception caught: %s" % (e))
        else:
            tolog("Not required to run the benchmark suite")

        return benchmark_subprocess

    def isDirectAccess(self, analysisJob, transferType=None):
        """ determine if direct access should be used """

        directIn, directInType = getDirectAccess()
        if not analysisJob and transferType and transferType != "direct":
            directIn = False

        return directIn

    def replaceLFNsWithTURLs(self, cmd, fname, inFiles, workdir, writetofile=""):
        """
        Replace all LFNs with full TURLs.
        This function is used with direct access. Athena requires a full TURL instead of LFN.
        """

        tolog("inside replaceLFNsWithTURLs()")
        turl_dictionary = {}  # { LFN: TURL, ..}
        if os.path.exists(fname):
            file_info_dictionary = mover.getFileInfoDictionaryFromXML(fname)
            tolog("file_info_dictionary=%s" % file_info_dictionary)
            for inputFile in inFiles:
                if inputFile in file_info_dictionary:
                    turl = file_info_dictionary[inputFile][0]
                    turl_dictionary[inputFile] = turl
                    if inputFile in cmd:
                        if turl.startswith('root://') and turl not in cmd:
                            cmd = cmd.replace(inputFile, turl)
                            tolog("Replaced '%s' with '%s' in the run command" % (inputFile, turl))
                else:
                    tolog("!!WARNING!!3434!! inputFile=%s not in dictionary=%s" % (inputFile, file_info_dictionary))

            tolog("writetofile=%s" % writetofile)
            tolog("turl_dictionary=%s" % turl_dictionary)
            # replace the LFNs with TURLs in the writeToFile input file list (if it exists)
            if writetofile and turl_dictionary:
                filenames = getWriteToInputFilenames(writetofile)
                tolog("filenames=%s" % filenames)
                for fname in filenames:
                    new_lines = []
                    path = os.path.join(workdir, fname)
                    if os.path.exists(path):
                        f = readFile(path)
                        tolog("readFile=%s" % f)
                        for line in f.split('\n'):
                            fname = os.path.basename(line)
                            if fname in turl_dictionary:
                                turl = turl_dictionary[fname]
                                new_lines.append(turl)
                            else:
                                if line:
                                    new_lines.append(line)

                        lines = '\n'.join(new_lines)
                        if lines:
                            writeFile(path, lines)
                            tolog("lines=%s" % lines)
                    else:
                        tolog("!!WARNING!!4546!! File does not exist: %s" % path)
        else:
            tolog("!!WARNING!!4545!! Could not find file: %s (cannot locate TURLs for direct access)" % fname)

        return cmd

    def executePayload(self, thisExperiment, runCommandList, job):
        """ execute the payload """

        # do not hide the proxy for PandaMover since it needs it or for sites that has sc.proxy = donothide
        # if 'DDM' not in jobSite.sitename and readpar('proxy') != 'donothide':
        #    # create the proxy guard object (must be created here before the sig2exc())
        #    proxyguard = ProxyGuard()
        #
        #    # hide the proxy
        #    hP_ret = proxyguard.hideProxy()
        #    if not hP_ret:
        #        tolog("Warning: Proxy exposed to payload")

        # If clone job, make sure that the events should be processed
        if job.cloneJob == "runonce":
            try:
                # If the event is still available, the go ahead and run the payload
                message = downloadEventRanges(job.jobId, job.jobsetID, job.taskID, url=self.__pandaserver)

                # Create a list of event ranges from the downloaded message
                event_ranges = self.extractEventRanges(message)

                # Are there any event ranges?
                if event_ranges == []:
                    tolog("!!WARNING!!2424!! This clone job was already executed")
                    exitMsg = "Already executed clone job"
                    res_tuple = (1, exitMsg)
                    res = (res_tuple[0], res_tuple[1], exitMsg)
                    job.result[0] = exitMsg
                    job.result[1] = 0 # transExitCode
                    job.result[2] = self.__error.ERR_EXECUTEDCLONEJOB # Pilot error code
                    return res, job, False, 0
                else:
                    tolog("Ok to execute clone job")
            except Exception, e:
                tolog("!1WARNING!!2323!! Exception caught: %s" % (e))

        # Run the payload process, which could take days to finish
        t0 = os.times()
        path = os.path.join(job.workdir, 't0_times.txt')
        if writeFile(path, str(t0)):
            tolog("Wrote %s to file %s" % (str(t0), path))
        else:
            tolog("!!WARNING!!3344!! Failed to write t0 to file, will not be able to calculate CPU consumption time on the fly")

        res_tuple = (0, 'Undefined')

        multi_trf = self.isMultiTrf(runCommandList)
        _stdout = job.stdout
        _stderr = job.stderr

        # Loop over all run commands (only >1 for multi-trfs)
        current_job_number = 0
        getstatusoutput_was_interrupted = False
        number_of_jobs = len(runCommandList)
        for cmd in runCommandList:
            current_job_number += 1

            # Create the stdout/err files
            if multi_trf:
                job.stdout = _stdout.replace(".txt", "_%d.txt" % (current_job_number))
                job.stderr = _stderr.replace(".txt", "_%d.txt" % (current_job_number))
            file_stdout, file_stderr = self.getStdoutStderrFileObjects(stdoutName=job.stdout, stderrName=job.stderr)
            if not (file_stdout and file_stderr):
                res_tuple = (1, "Could not open stdout/stderr files, piping not possible")
                tolog("!!WARNING!!2222!! %s" % (res_tuple[1]))
                break

            try:
                # Add the full job command to the job_setup.sh file
                to_script = cmd.replace(";", ";\n")
                thisExperiment.updateJobSetupScript(job.workdir, to_script=to_script)

                # For direct access in prod jobs, we need to substitute the input file names with the corresponding TURLs
                try:
                    analysisJob = job.isAnalysisJob()
                    directIn = self.isDirectAccess(analysisJob, transferType=job.transferType)
                    tolog("analysisJob=%s" % analysisJob)
                    tolog("directIn=%s" % directIn)
                    if not analysisJob and directIn:
                        # replace the LFNs with TURLs in the job command
                        # (and update the writeToFile input file list if it exists)
                        _fname = os.path.join(job.workdir, "PoolFileCatalog.xml")
                        cmd = self.replaceLFNsWithTURLs(cmd, _fname, job.inFiles, job.workdir, writetofile=job.writetofile)

                except Exception, e:
                    tolog("Caught exception: %s" % e)

                tolog("Executing job command %d/%d" % (current_job_number, number_of_jobs))

                # Hack to replace Archive_tf
                # if job.trf == 'Archive_tf.py' or job.trf == 'Dummy_tf.py':
                #     cmd = 'sleep 1'
                #     tolog('Will execute a dummy sleep command instead of %s' % job.trf)

                # Start the subprocess
                main_subprocess = self.getSubprocess(thisExperiment, cmd, stdout=file_stdout, stderr=file_stderr)

                if main_subprocess:

                    path = os.path.join(job.workdir, 'cpid.txt')
                    if writeFile(path, str(main_subprocess.pid)):
                        tolog("Wrote cpid=%s to file %s" % (main_subprocess.pid, path))
                    time.sleep(2)

                    # Start the utility if required
                    utility_subprocess = self.getUtilitySubprocess(thisExperiment, cmd, main_subprocess.pid, job)
                    utility_subprocess_launches = 1

                    # Loop until the main subprocess has finished
                    while main_subprocess.poll() is None:
                        # Take a short nap
                        time.sleep(5)

                        # Make sure that the utility subprocess is still running
                        if utility_subprocess:
                            # Take another short nap
                            time.sleep(5)
                            if not utility_subprocess.poll() is None:
                                # If poll() returns anything but None it means that the subprocess has ended - which it should not have done by itself
                                # Unless it was killed by the Monitor along with all other subprocesses
                                if not os.path.exists(os.path.join(job.workdir, "MEMORYEXCEEDED")) and not os.path.exists(os.path.join(job.workdir, "JOBWILLBEKILLED")):
                                    if utility_subprocess_launches <= 5:
                                        tolog("!!WARNING!!4343!! Dectected crashed utility subprocess - will restart it")
                                        utility_subprocess = self.getUtilitySubprocess(thisExperiment, cmd, main_subprocess.pid, job)
                                        utility_subprocess_launches += 1
                                    elif utility_subprocess_launches <= 6:
                                        tolog("!!WARNING!!4343!! Dectected crashed utility subprocess - too many restarts, will not restart again")
                                        utility_subprocess_launches += 1
                                        utility_subprocess = None
                                    else:
                                        pass
                                else:
                                    tolog("Detected lockfile MEMORYEXCEEDED: will not restart utility")
                                    utility_subprocess = None

                    # Stop the utility
                    if utility_subprocess:
                        utility_subprocess.send_signal(signal.SIGUSR1)
                        tolog("Terminated the utility subprocess")

                        _nap = 10
                        tolog("Taking a short nap (%d s) to allow the utility to finish writing to the summary file" % (_nap))
                        time.sleep(_nap)

                        # Copy the output JSON to the pilots init dir
                        _path = "%s/%s" % (job.workdir, thisExperiment.getUtilityJSONFilename())
                        if os.path.exists(_path):
                            try:
                                copy2(_path, self.__pilot_initdir)
                            except Exception, e:
                                tolog("!!WARNING!!2222!! Caught exception while trying to copy JSON files: %s" % (e))
                            else:
                                tolog("Copied %s to pilot init dir" % (_path))
                        else:
                            tolog("File %s was not created" % (_path))

                    # Handle main subprocess errors
                    try:
                        stdout = open(job.stdout, 'r')
                        if main_subprocess:
                            res_tuple = (main_subprocess.returncode, tail(stdout))
                        else:
                            res_tuple = (1, "Popen process does not exist (see stdout/err)")
                    except Exception, e:
                        tolog("!!WARNING!!3002!! Failed during tail operation: %s" % (e))
                    else:
                        tolog("Tail:\n%s" % (res_tuple[1]))
                        stdout.close()

                else:
                    res_tuple = (1, "Popen ended prematurely (payload command failed to execute, see stdout/err)")
                    tolog("!!WARNING!!3001!! %s" % (res_tuple[1]))

            except Exception, e:
                tolog("!!WARNING!!3000!! Failed to run command: %s" % (e))
                getstatusoutput_was_interrupted = True
                if self.__failureCode:
                    job.result[2] = self.__failureCode
                    tolog("!!FAILED!!3000!! Failure code: %d" % (self.__failureCode))
                    break
            else:
                if res_tuple[0] == 0:
                    tolog("Job command %d/%d finished" % (current_job_number, number_of_jobs))
                else:
                    tolog("Job command %d/%d failed: res = %s" % (current_job_number, number_of_jobs, str(res_tuple)))
                    break

        t1 = os.times()
        cpuconsumptiontime = get_cpu_consumption_time(t0)
        job.cpuConsumptionTime = int(cpuconsumptiontime)
        job.cpuConsumptionUnit = 's'
        job.cpuConversionFactor = 1.0

        tolog("Job CPU usage: %s %s" % (job.cpuConsumptionTime, job.cpuConsumptionUnit))
        tolog("Job CPU conversion factor: %1.10f" % (job.cpuConversionFactor))
        job.timeExe = int(round(t1[4] - t0[4]))

        tolog("Original exit code: %d" % (res_tuple[0]))
        tolog("Exit code: %d (returned from OS)" % (res_tuple[0]%255))

        # check the job report for any exit code that should replace the res_tuple[0]
        res0, exitAcronym, exitMsg = self.getTrfExitInfo(res_tuple[0], job.workdir)
        res = (res0, res_tuple[1], exitMsg)

        # dump an extract of the payload output
        if number_of_jobs > 1:
            _stdout = job.stdout
            _stderr = job.stderr
            _stdout = _stdout.replace(".txt", "_N.txt")
            _stderr = _stderr.replace(".txt", "_N.txt")
            tolog("NOTE: For %s output, see files %s, %s (N = [1, %d])" % (job.payload, _stdout, _stderr, number_of_jobs))
        else:
            tolog("NOTE: For %s output, see files %s, %s" % (job.payload, job.stdout, job.stderr))

        # JEM job-end callback
        try:
            from JEMstub import notifyJobEnd2JEM
            notifyJobEnd2JEM(job, tolog)
        except:
            pass # don't care

        # restore the proxy
        #if hP_ret:
        #    rP_ret = proxyguard.restoreProxy()
        #    if not rP_ret:
        #        tolog("Warning: Problems with storage can occur since proxy could not be restored")
        #    else:
        #        hP_ret = False
        #        tolog("ProxyGuard has finished successfully")

        return res, job, getstatusoutput_was_interrupted, current_job_number

    def moveTrfMetadata(self, workdir, jobId):
        """ rename and copy the trf metadata """

        oldMDName = "%s/metadata.xml" % (workdir)
        _filename = "metadata-%s.xml.PAYLOAD" % (jobId)
        newMDName = "%s/%s" % (workdir, _filename)
        try:
            os.rename(oldMDName, newMDName)
        except:
            tolog("Warning: Could not open the original %s file, but harmless, pass it" % (oldMDName))
            pass
        else:
            tolog("Renamed %s to %s" % (oldMDName, newMDName))
            # now move it to the pilot work dir
            try:
                copy2(newMDName, "%s/%s" % (self.__pworkdir, _filename))
            except Exception, e:
                tolog("Warning: Could not copy %s to site work dir: %s" % (_filename, str(e)))
            else:
                tolog("Metadata was transferred to site work dir: %s/%s" % (self.__pworkdir, _filename))

    def createFileMetadata(self, outFiles, job, outsDict, dsname, datasetDict, sitename, analysisJob=False, fromJSON=False):
        """ create the metadata for the output + log files """
        # Note: if file names and guids were extracted from the jobReport.json file, then the getOutFilesGuids() should not be called

        ec = 0

        # get/assign guids to the output files
        if outFiles:
            if not pUtil.isBuildJob(outFiles) and not fromJSON:
                ec, job.pilotErrorDiag, job.outFilesGuids = RunJobUtilities.getOutFilesGuids(job.outFiles, job.workdir, self.__experiment)
                if ec:
                    # missing PoolFileCatalog (only error code from getOutFilesGuids)
                    return ec, job, None
            else:
                tolog("Will not use PoolFileCatalog to get guid")
        else:
            tolog("This job has no output files")

        # get the file sizes and checksums for the local output files
        # WARNING: any errors are lost if occur in getOutputFileInfo()
        ec, pilotErrorDiag, fsize, checksum = pUtil.getOutputFileInfo(list(outFiles), "adler32", skiplog=True, logFile=job.logFile)
        if ec != 0:
            tolog("!!FAILED!!2999!! %s" % (pilotErrorDiag))
            self.failJob(job.result[1], ec, job, pilotErrorDiag=pilotErrorDiag)

        if job.tarFileGuid and len(job.tarFileGuid.strip()):
             guid = job.tarFileGuid
        elif self.__logguid:
            guid = self.__logguid
        else:
            guid = job.tarFileGuid

        # create preliminary metadata (no metadata yet about log file - added later in pilot.py)
        _fname = "%s/metadata-%s.xml" % (job.workdir, job.jobId)
        try:
            _status = pUtil.PFCxml(job.experiment, _fname, list(job.outFiles), fguids=job.outFilesGuids, fntag="lfn", alog=job.logFile, alogguid=guid,\
                                   fsize=fsize, checksum=checksum, analJob=analysisJob, logToOS=job.putLogToOS)
        except Exception, e:
            pilotErrorDiag = "PFCxml failed due to problematic XML: %s" % (e)
            tolog("!!WARNING!!1113!! %s" % (pilotErrorDiag))
            self.failJob(job.result[1], error.ERR_MISSINGGUID, job, pilotErrorDiag=pilotErrorDiag)
        else:
            if not _status:
                pilotErrorDiag = "Missing guid(s) for output file(s) in metadata"
                tolog("!!FAILED!!2999!! %s" % (pilotErrorDiag))
                self.failJob(job.result[1], error.ERR_MISSINGGUID, job, pilotErrorDiag=pilotErrorDiag)

        tolog("..............................................................................................................")
        tolog("Created %s with:" % (_fname))
        tolog(".. log            : %s (to be transferred)" % (job.logFile))
        tolog(".. log guid       : %s" % (guid))
        tolog(".. out files      : %s" % str(job.outFiles))
        tolog(".. out file guids : %s" % str(job.outFilesGuids))
        tolog(".. fsize          : %s" % str(fsize))
        tolog(".. checksum       : %s" % str(checksum))
        tolog("..............................................................................................................")

        # convert the preliminary metadata-<jobId>.xml file to OutputFiles-<jobId>.xml for NG and for CERNVM
        # note: for CERNVM this is only really needed when CoPilot is used
        if os.environ.has_key('Nordugrid_pilot') or sitename == 'CERNVM':
            if RunJobUtilities.convertMetadata4NG(os.path.join(job.workdir, job.outputFilesXML), _fname, outsDict, dsname, datasetDict):
                tolog("Metadata has been converted to NG/CERNVM format")
            else:
                job.pilotErrorDiag = "Could not convert metadata to NG/CERNVM format"
                tolog("!!WARNING!!1999!! %s" % (job.pilotErrorDiag))

        # try to build a file size and checksum dictionary for the output files
        # outputFileInfo: {'a.dat': (fsize, checksum), ...}
        # e.g.: file size for file a.dat: outputFileInfo['a.dat'][0]
        # checksum for file a.dat: outputFileInfo['a.dat'][1]
        try:
            # remove the log entries
            _fsize = fsize[1:]
            _checksum = checksum[1:]
            outputFileInfo = dict(zip(job.outFiles, zip(_fsize, _checksum)))
        except Exception, e:
            tolog("!!WARNING!!2993!! Could not create output file info dictionary: %s" % str(e))
            outputFileInfo = {}
        else:
            tolog("Output file info dictionary created: %s" % str(outputFileInfo))

        return ec, job, outputFileInfo

    def isArchive(self, zipmap):
        """
        Is the archive zipmap populated?
        """

        if zipmap:
            archive = True
        else:
            archive = False

        return archive

    def getDatasets(self, job, zipmap=None):
        """ get the datasets for the output files """

        # get the default dataset
        if job.destinationDblock and job.destinationDblock[0] != 'NULL' and job.destinationDblock[0] != ' ':
            dsname = job.destinationDblock[0]
        else:
            dsname = "%s-%s-%s" % (time.localtime()[0:3]) # pass it a random name

        # create the dataset dictionary
        # (if None, the dsname above will be used for all output files)
        archive = self.isArchive(zipmap)
        datasetDict = getDatasetDict(job.outFiles, job.destinationDblock, job.logFile, job.logDblock, archive=archive)
        if datasetDict:
            tolog("Dataset dictionary has been verified")
        else:
            tolog("Dataset dictionary could not be verified, output files will go to: %s" % (dsname))

        return dsname, datasetDict


    def stageOut_new(self,
                     job,
                     jobSite,
                     outs,            # somehow prepared validated output files list (logfiles not included)
                     analysisJob,     # not used, --> job.isAnalysisJob() should be used instead
                     dsname,          # default dataset name to be used if file.destinationDblock is not set
                     datasetDict,     # validated dict to resolve dataset name: datasetDict = dict(zip(outputFiles, destinationDblock)) + (logFile, logFileDblock)
                     outputFileInfo   # validated dict: outputFileInfo = dict(zip(job.outFiles, zip(_fsize, _checksum)))
                                      # can be calculated in Mover directly while transferring??
                     ):
        """
            perform the stage-out
            :return: (rcode, job, rf, latereg=False) # latereg is always False
            note: returning `job` is useless since reference passing
        """

        # warning: in main workflow if jobReport is used as source for output file it completely overwtites job.outFiles ==> suppose it's wrong behaviour .. do extend outFiles instead.
        # extend job.outData from job.outFiles (consider extra files extractOutputFilesFromJSON in the main workflow)

        #  populate guid and dataset values for job.outData
        # copy all extra files from job.outFiles into structured job.outData

        job._sync_outdata() # temporary work-around, reuse old workflow that populates job.outFilesGuids

        try:
            t0 = os.times()
            rc, job.pilotErrorDiag, rf, _dummy, job.filesNormalStageOut, job.filesAltStageOut = mover.put_data_new(job, jobSite, stageoutTries=self.__stageoutretry, log_transfer=False, pinitdir=self.__pilot_initdir)
            t1 = os.times()

            job.timeStageOut = int(round(t1[4] - t0[4]))

        except Exception, e:
            t1 = os.times()
            job.timeStageOut = int(round(t1[4] - t0[4]))

            error = "Put function can not be called for staging out: %s, trace=%s" % (e, traceback.format_exc())
            tolog(error)

            rc = PilotErrors.ERR_PUTFUNCNOCALL
            job.setState(["holding", job.result[1], rc])

            return rc, job, None, False

        tolog("Put function returned code: %s" % rc)

        if rc:

            if job.pilotErrorDiag:
                job.pilotErrorDiag = job.pilotErrorDiag[-256:]

            # check if the job is recoverable?
            _state, _msg = "failed", "FAILED"
            if PilotErrors.isRecoverableErrorCode(rc) and '(unrecoverable)' not in job.pilotErrorDiag:
                _state, _msg = "holding", "WARNING"

            job.setState([_state, job.result[1], rc])

            tolog(" -- %s: %s" % (_msg, PilotErrors.getErrorStr(rc)))
        else:

            job.setState(["finished", 0, 0])

            # create a weak lockfile meaning that file transfer worked
            # (useful for job recovery if activated) in the job workdir
            createLockFile(True, jobSite.workdir, lockfile="ALLFILESTRANSFERRED")
            # create another lockfile in the site workdir since a transfer failure can still occur during the log transfer
            # and a later recovery attempt will fail (job workdir will not exist at that time)
            createLockFile(True, self.__pworkdir, lockfile="ALLFILESTRANSFERRED")

        return rc, job, rf, False


    @mover.use_newmover(stageOut_new)
    def stageOut(self, job, jobSite, outs, analysisJob, dsname, datasetDict, outputFileInfo):
        """ perform the stage-out """

        error = PilotErrors()
        pilotErrorDiag = ""
        rc = 0
        latereg = False
        rf = None

        # generate the xml for the output files and the site mover
        pfnFile = "OutPutFileCatalog.xml"
        try:
            _status = pUtil.PFCxml(job.experiment, pfnFile, outs, fguids=job.outFilesGuids, fntag="pfn")
        except Exception, e:
            job.pilotErrorDiag = "PFCxml failed due to problematic XML: %s" % (e)
            tolog("!!WARNING!!1113!! %s" % (job.pilotErrorDiag))
            return error.ERR_MISSINGGUID, job, rf, latereg
        else:
            if not _status:
                job.pilotErrorDiag = "Metadata contains missing guid(s) for output file(s)"
                tolog("!!WARNING!!2999!! %s" % (job.pilotErrorDiag))
                return error.ERR_MISSINGGUID, job, rf, latereg

        tolog("Using the newly-generated %s/%s for put operation" % (job.workdir, pfnFile))

        # the cmtconfig is needed by at least the xrdcp site mover
        cmtconfig = getCmtconfig(job.cmtconfig)

        rs = "" # return string from put_data with filename in case of transfer error
        tin_0 = os.times()
        try:
            rc, job.pilotErrorDiag, rf, rs, job.filesNormalStageOut, job.filesAltStageOut, os_bucket_id = mover.mover_put_data("xmlcatalog_file:%s" % (pfnFile), dsname, jobSite.sitename,\
                                             jobSite.computingElement, analysisJob=analysisJob, pinitdir=self.__pilot_initdir, proxycheck=self.__proxycheckFlag, datasetDict=datasetDict,\
                                             outputDir=self.__outputDir, outputFileInfo=outputFileInfo, stageoutTries=self.__stageoutretry, cmtconfig=cmtconfig, job=job)
            tin_1 = os.times()
            job.timeStageOut = int(round(tin_1[4] - tin_0[4]))
        except Exception, e:
            tin_1 = os.times()
            job.timeStageOut = int(round(tin_1[4] - tin_0[4]))

            if 'format_exc' in traceback.__all__:
                trace = traceback.format_exc()
                pilotErrorDiag = "Put function can not be called for staging out: %s, %s" % (str(e), trace)
            else:
                tolog("traceback.format_exc() not available in this python version")
                pilotErrorDiag = "Put function can not be called for staging out: %s" % (str(e))
            tolog("!!WARNING!!3000!! %s" % (pilotErrorDiag))

            rc = error.ERR_PUTFUNCNOCALL
            job.setState(["holding", job.result[1], rc])
        else:
            if job.pilotErrorDiag != "":
                if job.pilotErrorDiag.startswith("Put error:"):
                    pre = ""
                else:
                    pre = "Put error: "
                job.pilotErrorDiag = pre + tailPilotErrorDiag(job.pilotErrorDiag, size=256-len("pilot: Put error: "))

            tolog("Put function returned code: %d" % (rc))
            if rc != 0:
                # remove any trailing "\r" or "\n" (there can be two of them)
                if rs != None:
                    rs = rs.rstrip()
                    tolog("Error string: %s" % (rs))

                # is the job recoverable?
                if error.isRecoverableErrorCode(rc):
                    _state = "holding"
                    _msg = "WARNING"
                else:
                    _state = "failed"
                    _msg = "FAILED"

                # look for special error in the error string
                if rs == "Error: string Limit exceeded 250":
                    tolog("!!%s!!3000!! Put error: file name string limit exceeded 250" % (_msg))
                    job.setState([_state, job.result[1], error.ERR_LRCREGSTRSIZE])
                else:
                    job.setState([_state, job.result[1], rc])

                tolog("!!%s!!1212!! %s" % (_msg, error.getErrorStr(rc)))
            else:
                # set preliminary finished (may be overwritten below)
                job.setState(["finished", 0, 0])

                # create a weak lockfile meaning that file transfer worked
                # (useful for job recovery if activated) in the job workdir
                createLockFile(True, jobSite.workdir, lockfile="ALLFILESTRANSFERRED")
                # create another lockfile in the site workdir since a transfer failure can still occur during the log transfer
                # and a later recovery attempt will fail (job workdir will not exist at that time)
                createLockFile(True, self.__pworkdir, lockfile="ALLFILESTRANSFERRED")

            if job.result[0] == "holding" and '(unrecoverable)' in job.pilotErrorDiag:
                job.result[0] = "failed"
                tolog("!!WARNING!!2999!! HOLDING state changed to FAILED since error is unrecoverable")

        return rc, job, rf, latereg

    def copyInputForFiles(self, workdir):
        """ """

        try:
            cmd = "cp %s/inputFor_* %s" % (self.__pilot_initdir, workdir)
            tolog("Executing command: %s" % (cmd))
            out = commands.getoutput(cmd)
        except IOError, e:
            pass
        tolog(out)

    def getStdoutStderrFileObjects(self, stdoutName="stdout.txt", stderrName="stderr.txt"):
        """ Create stdout/err file objects """

        try:
            stdout = open(os.path.join(os.getcwd(), stdoutName), "w")
            stderr = open(os.path.join(os.getcwd(), stderrName), "w")
        except Exception, e:
            tolog("!!WARNING!!3330!! Failed to open stdout/err files: %s" % (e))
            stdout = None
            stderr = None

        return stdout, stderr

    def getSubprocess(self, thisExperiment, runCommand, stdout=None, stderr=None):
        """ Execute a command as a subprocess """

        # Execute and return the subprocess object
        return thisExperiment.getSubprocess(runCommand, stdout=stdout, stderr=stderr)

    # Methods used by event service RunJob* modules ..............................................................

    def stripSetupCommand(self, cmd, trfName):
        """ Remove the trf part of the setup command """

        location = cmd.find(trfName)
        return cmd[:location]

    def executeMakeRunEventCollectionScript(self, cmd, eventcollection_filename):
        """ Define and execute the event collection script """

        cmd += "get_files -jo %s" % (eventcollection_filename)
        tolog("Execute command: %s" % (cmd))

        # WARNING: PUT A TIMER AROUND THIS COMMAND
        rc, rs = commands.getstatusoutput(cmd)

        return rc, rs

    def prependMakeRunEventCollectionScript(self, input_file, output_file, eventcollection_filename):
        """ Prepend the event collection script """

        status = False
        eventcollection_filename_mod = ""

        with open(eventcollection_filename) as f1:
            eventcollection_filename_mod = eventcollection_filename.replace(".py",".2.py")
            with open(eventcollection_filename_mod, "w") as f2:
                f2.write("EvtMax = -1\n")
                f2.write("In = [ \'%s\' ]\n" % (input_file))
                f2.write("Out = \'%s\'\n" % (output_file))
                for line in f1:
                    f2.write(line)
                f2.close()
                f1.close()
                status = True

        return status, eventcollection_filename_mod

    def executeTAGFileCommand(self, cmd, eventcollection_filename_mod):
        """ Execute the TAG file creation script using athena """

        cmd += "athena.py %s >MakeRunEventCollection-stdout.txt" % (eventcollection_filename_mod)
        tolog("Executing command: %s" % (cmd))

        # WARNING: PUT A TIMER AROUND THIS COMMAND
        rc, rs = commands.getstatusoutput(cmd)

        return rc, rs

    def swapAthenaProcNumber(self, swap_value):
        """ Swap the current ATHENA_PROC_NUMBER so that it does not upset the job """
        # Note: only needed during TAG file creation

        athena_proc_number = 0
        try:
            athena_proc_number = int(os.environ['ATHENA_PROC_NUMBER'])
        except Exception, e:
            tolog("ATHENA_PROC_NUMBER not defined, setting it to: %s" % (swap_value))
            os.environ['ATHENA_PROC_NUMBER'] = str(swap_value)
        else:
            if swap_value == 0:
                del os.environ['ATHENA_PROC_NUMBER']
                tolog("Unset ATHENA_PROC_NUMBER")
            else:
                os.environ['ATHENA_PROC_NUMBER'] = str(swap_value)
                tolog("ATHENA_PROC_NUMBER swapped from \'%d\' to \'%d\'" % (athena_proc_number, swap_value))

        return athena_proc_number

    def createTAGFile(self, jobExecutionCommand, trfName, inFiles, eventcollection_filename):
        """ Create a TAG file """

        tag_file = ""
        tag_file_guid = getGUID()

        # We cannot have ATHENA_PROC_NUMBER set to a value larger than 1, since that will
        # activate AthenaMP. Reset it for now, and swap it back at the end of this method
        athena_proc_number = self.swapAthenaProcNumber(0)

        # Remove everything after the trf command from the job execution command
        cmd = self.stripSetupCommand(jobExecutionCommand, trfName)
        tolog("Stripped command: %s" % (cmd))

        # Define and execute the event collection script
        if cmd != "":
            rc, rs = self.executeMakeRunEventCollectionScript(cmd, eventcollection_filename)
            # Prepend the event collection script
            if rc == 0:
                input_file = inFiles[0]
                tag_file = input_file + ".TAG"
                status, eventcollection_filename_mod = self.prependMakeRunEventCollectionScript(input_file, tag_file, eventcollection_filename)

                # Finally create the TAG file
                if status:
                    rc, rs = self.executeTAGFileCommand(cmd, eventcollection_filename_mod)
                    if rc != 0:
                        tolog("!!WARNING!!3337!! Failed to create TAG file: rc=%d, rs=%s" % (rc, rs))
                        tag_file = ""
            else:
                tolog("!!WARNING!!3339!! Failed to download %s: rc=%d, rs=%s " % (eventcollection_filename, rc, rs))
        else:
            tolog("!!WARNING!!3330!! Failed to strip the job execution command, cannot create TAG file")

        # Now swap the ATHENA_PROC_NUMBER since it is needed for activating AthenaMP
        dummy = self.swapAthenaProcNumber(athena_proc_number)

        return tag_file, tag_file_guid

    def extractEventRanges(self, message):
        """ Extract all event ranges from the server message """

        # This function will return a list of event range dictionaries

        event_ranges = []

        try:
            event_ranges = loads(message)
        except Exception, e:
            tolog("Could not extract any event ranges: %s" % (e))

        return event_ranges

    def unzipStagedFiles(self, job):
        for inputZipFile in job.inputZipFiles:
            inputZipFile = os.path.join(job.workdir, inputZipFile)
            command = "tar -xf %s -C %s" % (inputZipFile, job.workdir)
            tolog("Unzip file: %s" % command)
            status, output = commands.getstatusoutput(command)
            tolog("status: %s, output: %s\n" % (status, output))

    # (end event service methods) ................................................................................

    def handleAdditionalOutFiles(self, job, analysisJob):
        """ Update output file lists in case there are additional output files in the jobReport """
        # Note: only for production jobs

        fromJSON = False
        extracted_output_files, extracted_guids = extractOutputFiles(analysisJob, job.workdir, job.allowNoOutput, job.outFiles, job.outFilesGuids)
        if extracted_output_files != []:
            tolog("Will update the output file lists since files were discovered in the job report (production job) or listed in allowNoOutput and do not exist (user job)")

            new_destinationDBlockToken = []
            new_destinationDblock = []
            new_scopeOut = []
            try:
                for f in extracted_output_files:
                    _destinationDBlockToken, _destinationDblock, _scopeOut = getDestinationDBlockItems(f, job.outFiles, job.destinationDBlockToken, job.destinationDblock, job.scopeOut)
                    new_destinationDBlockToken.append(_destinationDBlockToken)
                    new_destinationDblock.append(_destinationDblock)
                    new_scopeOut.append(_scopeOut)
            except Exception, e:
                tolog("!!WARNING!!3434!! Exception caught: %s" % (e))
            else:
                # Finally replace the output file lists
                job.outFiles = extracted_output_files
                job.destinationDblock = new_destinationDblock
                job.destinationDBlockToken = new_destinationDBlockToken
                job.scopeOut = new_scopeOut
                tolog("Updated: job.outFiles=%s" % str(extracted_output_files))
                tolog("Updated: job.destinationDblock=%s" % str(job.destinationDblock))
                tolog("Updated: job.destinationDBlockToken=%s" % str(job.destinationDBlockToken))
                tolog("Updated: job.scopeOut=%s" % str(job.scopeOut))
                if extracted_guids != []:
                    fromJSON = True
                    job.outFilesGuids = extracted_guids
                    tolog("Updated: job.outFilesGuids=%s" % str(job.outFilesGuids))
                else:
                    tolog("Empty extracted guids list")

        return job, fromJSON

    def createArchives(self, output_files, zipmapString, workdir):
        """ Create archives for the files in the zip map """
        # The zip_map dictionary itself is also created and returned by this function
        # Note that the files are not to be further compressed (already assumed to be compressed)

        zip_map = None
        archive_names = None

        if zipmapString != "":
            zip_map = job.populateZipMap(output_files, zipmapString)

            # Zip the output files according to the zip map
            import zipfile
            cwd = os.getcwd()
            os.chdir(job.workdir)
            for archive in zip_map.keys():
                tolog("Creating zip archive %s for files %s" % (archive, zip_map[archive]))
                fname = os.path.join(workdir, archive)
                zf = zipfile.ZipFile(fname, mode='w', compression=zipfile.ZIP_STORED, allowZip64=True) # zero compression
                for content_file in zip_map[archive]:
                    try:
                        tolog("Adding %s to archive .." % (content_file))
                        zf.write(content_file)
                    except Exception, e:
                        tolog("!!WARNING!!3333!! Failed to add file %s to archive - aborting: %s" % (content_file, e))
                        zip_map = None
                        break
                if zf:
                    zf.close()
            os.chdir(cwd)
            if zip_map:
                archive_names = zip_map.keys()

        return zip_map, archive_names

    def cleanupForZip(self, zip_map, archive_names, job, outs, outputFileInfo, datasetDict):
        """ Remove redundant output files and update file lists """

        for archive in archive_names:
            # remove zipped output files from disk
            file_indices = []
            for filename in zip_map[archive]:
                fname = os.path.join(job.workdir, filename)
                try:
                    os.remove("%s" % (fname))
                except Exception,e:
                    tolog("!!WARNING!!3000!! Failed to delete file %s: %s" % (fname, str(e)))
                    pass

                # find the list index for the file (we need to remove the related file info from several lists)
                if filename in job.outFiles:
                    # store the file index and remove the file from the outs list
                    file_indices.append(job.outFiles.index(filename))
                    outs.remove(filename)
                else:
                    tolog("!!WARNING!!3454!! Failed to locate file %s in outFiles list" % (filename))

                # remove 'filename' key from dictionaries if it exists
                dummy = outputFileInfo.pop(filename, None)
                dummy = datasetDict.pop(filename, None)

            # now remove the file from the related lists (in reverse order)
            for index in reversed(file_indices):
                del job.outFiles[index]
                del job.outFilesGuids[index]
                del job.destinationDblock[index]
                del job.destinationDBlockToken[index]
                del job.scopeOut[index]

        return job, outs, outputFileInfo

# main process starts here
if __name__ == "__main__":

    # Get error handler
    error = PilotErrors()

    # Get runJob object
    runJob = RunJob()

    # Define a new parent group
    os.setpgrp()

    # Protect the runJob code with exception handling
    hP_ret = False
    try:
        # always use this filename as the new jobDef module name
        import newJobDef

        jobSite = Site.Site()

        return_tuple = runJob.argumentParser()
        tolog("argumentParser returned: %s" % str(return_tuple))
        jobSite.setSiteInfo(return_tuple)

#            jobSite.setSiteInfo(argParser(sys.argv[1:]))

        # reassign workdir for this job
        jobSite.workdir = jobSite.wntmpdir

        if runJob.getPilotLogFilename() != "":
            pUtil.setPilotlogFilename(runJob.getPilotLogFilename())

        # set node info
        node = Node.Node()
        node.setNodeName(os.uname()[1])
        node.collectWNInfo(jobSite.workdir)

        # redirect stder
        sys.stderr = open("%s/runjob.stderr" % (jobSite.workdir), "w")

        tolog("Current job workdir is: %s" % os.getcwd())
        tolog("Site workdir is: %s" % jobSite.workdir)

        # get the experiment object
        thisExperiment = getExperiment(runJob.getExperiment())
        tolog("RunJob will serve experiment: %s" % (thisExperiment.getExperiment()))

        # set the cache (used e.g. by LSST)
        if runJob.getCache():
            thisExperiment.setCache(runJob.getCache())

        JR = JobRecovery()
        try:
            job = Job.Job()
            job.workdir = jobSite.workdir
            job.setJobDef(newJobDef.job)
            job.workdir = jobSite.workdir
            job.experiment = runJob.getExperiment()
            # figure out and set payload file names
            job.setPayloadName(thisExperiment.getPayloadName(job))
            logGUID = newJobDef.job.get('logGUID', "")
            if logGUID != "NULL" and logGUID != "":
                job.tarFileGuid = logGUID
        except Exception, e:
            pilotErrorDiag = "Failed to process job info: %s" % str(e)
            tolog("!!WARNING!!3000!! %s" % (pilotErrorDiag))
            runJob.failJob(0, error.ERR_UNKNOWN, job, pilotErrorDiag=pilotErrorDiag)

        # prepare for the output file data directory
        # (will only created for jobs that end up in a 'holding' state)
        job.datadir = runJob.getParentWorkDir() + "/PandaJob_%s_data" % (job.jobId)

        # register cleanup function
        atexit.register(runJob.cleanup, job)

        # to trigger an exception so that the SIGTERM signal can trigger cleanup function to run
        # because by default signal terminates process without cleanup.
        def sig2exc(sig, frm):
            """ signal handler """

            error = PilotErrors()
            runJob.setGlobalPilotErrorDiag("!!FAILED!!3000!! SIGTERM Signal %s is caught in child pid=%d!\n" % (sig, os.getpid()))
            tolog(runJob.getGlobalPilotErrorDiag())
            if sig == signal.SIGTERM:
                runJob.setGlobalErrorCode(error.ERR_SIGTERM)
            elif sig == signal.SIGQUIT:
                runJob.setGlobalErrorCode(error.ERR_SIGQUIT)
            elif sig == signal.SIGSEGV:
                runJob.setGlobalErrorCode(error.ERR_SIGSEGV)
            elif sig == signal.SIGXCPU:
                runJob.setGlobalErrorCode(error.ERR_SIGXCPU)
            elif sig == signal.SIGBUS:
                runJob.setGlobalErrorCode(error.ERR_SIGBUS)
            elif sig == signal.SIGUSR1:
                runJob.setGlobalErrorCode(error.ERR_SIGUSR1)
            else:
                runJob.setGlobalErrorCode(error.ERR_KILLSIGNAL)
            runJob.setFailureCode(runJob.getGlobalErrorCode())
            # print to stderr
            print >> sys.stderr, runJob.getGlobalPilotErrorDiag()
            raise SystemError(sig)

        signal.signal(signal.SIGTERM, sig2exc)
        signal.signal(signal.SIGQUIT, sig2exc)
        signal.signal(signal.SIGSEGV, sig2exc)
        signal.signal(signal.SIGXCPU, sig2exc)
        signal.signal(signal.SIGUSR1, sig2exc)
        signal.signal(signal.SIGBUS, sig2exc)

        # see if it's an analysis job or not
        analysisJob = job.isAnalysisJob()
        if analysisJob:
            tolog("User analysis job")
        else:
            tolog("Production job")
        tolog("runJob received a job with prodSourceLabel=%s" % (job.prodSourceLabel))

        # setup starts here ................................................................................

        # update the job state file
        job.jobState = "setup"
        _retjs = JR.updateJobStateTest(job, jobSite, node, mode="test")

        # send [especially] the process group back to the pilot
        job.setState([job.jobState, 0, 0])
        rt = RunJobUtilities.updatePilotServer(job, runJob.getPilotServer(), runJob.getPilotPort())

        # in case zipmaps will be used for the output files, save the zipmap string for later use and remove it from the jobPars
        if "ZIP_MAP" in job.jobPars:
            job.jobPars, zipmapString = job.removeZipMapString(job.jobPars)
            tolog("Extracted zipmap string from jobPars: %s (removed from jobPars)" % (zipmapString))
        else:
            zipmapString = ""

        # prepare the setup and get the run command list
        ec, runCommandList, job, multi_trf = runJob.setup(job, jobSite, thisExperiment)
        if ec != 0:
            tolog("!!WARNING!!2999!! runJob setup failed: %s" % (job.pilotErrorDiag))
            runJob.failJob(0, ec, job, pilotErrorDiag=job.pilotErrorDiag)
        tolog("Setup has finished successfully")

        # job has been updated, display it again
        job.displayJob()

        # (setup ends here) ................................................................................

        tolog("Setting stage-in state until all input files have been copied")
        job.setState(["stagein", 0, 0])
        # send the special setup string back to the pilot (needed for the log transfer on xrdcp systems)
        rt = RunJobUtilities.updatePilotServer(job, runJob.getPilotServer(), runJob.getPilotPort())

        # stage-in .........................................................................................

        # benchmark ........................................................................................

        # Launch the benchmark, let it execute during setup + stage-in
        benchmark_subprocess = runJob.getBenchmarkSubprocess(node, job.coreCount, job.workdir, jobSite.sitename)

        # update the job state file
        job.jobState = "stagein"
        _retjs = JR.updateJobStateTest(job, jobSite, node, mode="test")

        # update copysetup[in] for production jobs if brokerage has decided that remote I/O should be used
        if job.transferType == 'direct' or job.transferType == 'fax':
            tolog('Brokerage has set transfer type to \"%s\" (remote I/O will be attempted for input files)' %\
                  (job.transferType))
            RunJobUtilities.updateCopysetups('', transferType=job.transferType)
            si = getSiteInformation(runJob.getExperiment())
            si.updateDirectAccess(job.transferType)

        # stage-in all input files (if necessary)
        job, ins, statusPFCTurl, usedFAXandDirectIO = runJob.stageIn(job, jobSite, analysisJob)
        if job.result[2] != 0:
            tolog("Failing job with ec: %d" % (ec))
            runJob.failJob(0, job.result[2], job, ins=ins, pilotErrorDiag=job.pilotErrorDiag)

        # after stageIn, all file transfer modes are known (copy_to_scratch, file_stager, remote_io)
        # consult the FileState file dictionary if cmd3 should be updated (--directIn should not be set if all
        # remote_io modes have been changed to copy_to_scratch as can happen with ByteStream files)
        # and update the run command list if necessary.
        # in addition to the above, if FAX is used as a primary site mover and direct access is enabled, then
        # the run command should not contain the --oldPrefix, --newPrefix options but use --usePFCTurl
        hasInput = job.inFiles != ['']
        runCommandList = RunJobUtilities.updateRunCommandList(runCommandList, runJob.getParentWorkDir(), job.jobId, statusPFCTurl, analysisJob, usedFAXandDirectIO, hasInput, job.prodDBlockToken)

        # copy any present @inputFor_* files from the pilot init dir to the rundirectory (used for ES merge jobs)
        #runJob.copyInputForFiles(job.workdir)

        # unzip the staged in file if necessary
        runJob.unzipStagedFiles(job)

        # (stage-in ends here) .............................................................................

        # Loop until the benchmark subprocess has finished
        if benchmark_subprocess:
            max_count = 6
            _sleep = 15
            count = 0
            while benchmark_subprocess.poll() is None:
                if count >= max_count:
                    benchmark_subprocess.send_signal(signal.SIGUSR1)
                    tolog("Terminated the benchmark since it ran for longer than %d s" % (max_count*_sleep))
                    break
                else:
                    count += 1

                    # Take a short nap
                    tolog("Benchmark suite has not finished yet, taking a %d s nap (iteration #%d/%d)" % (_sleep, count, max_count))
                    time.sleep(_sleep)

        # (benchmark ends here) ............................................................................

        # change to running state since all input files have been staged
        tolog("Changing to running state since all input files have been staged")
        job.setState(["running", 0, 0])
        rt = RunJobUtilities.updatePilotServer(job, runJob.getPilotServer(), runJob.getPilotPort())

        # update the job state file
        job.jobState = "running"
        _retjs = JR.updateJobStateTest(job, jobSite, node, mode="test")

        # run the job(s) ...................................................................................

        # set ATLAS_CONDDB if necessary, and other env vars
        RunJobUtilities.setEnvVars(jobSite.sitename)

        # execute the payload
        res, job, getstatusoutput_was_interrupted, current_job_number = runJob.executePayload(thisExperiment, runCommandList, job)

        # payload error handling
        ed = ErrorDiagnosis()
        job = ed.interpretPayload(job, res, getstatusoutput_was_interrupted, current_job_number, runCommandList, runJob.getFailureCode())
        if job.result[1] != 0 or job.result[2] != 0:
            if job.eventServiceMerge:
                if runJob.corruptedFiles:
                    job.corruptedFiles = ','.join([e['lfn'] for e in runJob.corruptedFiles])
                    job.result[2] = runJob.corruptedFiles[0]['status_code']
                else:
                    job.result[2] = PilotErrors.ERR_ESRECOVERABLE
            runJob.failJob(job.result[1], job.result[2], job, pilotErrorDiag=job.pilotErrorDiag)

        # stage-out ........................................................................................

        # update the job state file
        job.jobState = "stageout"
        _retjs = JR.updateJobStateTest(job, jobSite, node, mode="test")

        # are there any additional output files created by the trf/payload? if so, the outut file list must be updated
        job, fromJSON = runJob.handleAdditionalOutFiles(job, analysisJob)

        # should any output be zipped? if so, the zipmapString was previously set (otherwise the returned variables are set to None)
        # zip_map, archive_names = runJob.createArchives(job.outFiles, zipmapString, job.workdir)
        zip_map = None
        if zip_map:
            # Add the zip archives to the output file lists
            job.outFiles, job.destinationDblock, job.destinationDBlockToken, job.scopeOut = job.addArchivesToOutput(zip_map,
                                                                                                                    job.inFiles,
                                                                                                                    job.outFiles,
                                                                                                                    job.dispatchDblock,
                                                                                                                    job.destinationDblock,
                                                                                                                    job.dispatchDBlockToken,
                                                                                                                    job.destinationDBlockToken,
                                                                                                                    job.scopeIn,
                                                                                                                    job.scopeOut)
            #job.outFiles, job.destinationDblock, job.destinationDBlockToken, job.scopeOut = job.addArchivesToOutput(zip_map, job.outFiles, job.destinationDblock, job.destinationDBlockToken, job.scopeOut)

        # verify and prepare and the output files for transfer
        ec, pilotErrorDiag, outs, outsDict = RunJobUtilities.prepareOutFiles(job.outFiles, job.logFile, job.workdir)
        if ec:
            # missing output file (only error code from prepareOutFiles)
            runJob.failJob(job.result[1], ec, job, pilotErrorDiag=pilotErrorDiag)
        tolog("outs=%s"%str(outs))
        tolog("outsDict=%s"%str(outsDict))

        # if payload leaves the input files, delete them explicitly
        if ins and not zip_map:
            ec = pUtil.removeFiles(job.workdir, ins)

        # update the current file states
        updateFileStates(outs, runJob.getParentWorkDir(), job.jobId, mode="file_state", state="created")
        dumpFileStates(runJob.getParentWorkDir(), job.jobId)
            
        # create xml string to pass to server
        outputFileInfo = {}
        if outs or (job.logFile and job.logFile != ''):
            # get the datasets for the output files
            dsname, datasetDict = runJob.getDatasets(job, zipmap=zip_map)

            tolog("datasetDict=%s"%str(datasetDict))

            # re-create the metadata.xml file, putting guids of ALL output files into it.
            # output files that miss guids from the job itself will get guids in PFCxml function

            # first rename and copy the trf metadata file for non-build jobs
            if not pUtil.isBuildJob(outs):
                runJob.moveTrfMetadata(job.workdir, job.jobId)

            # create the metadata for the output + log files
            ec = 0
            try:
                ec, job, outputFileInfo = runJob.createFileMetadata(list(outs), job, outsDict, dsname, datasetDict, jobSite.sitename, analysisJob=analysisJob, fromJSON=fromJSON)
            except Exception as e:
                job.pilotErrorDiag = "Exception caught: %s" % e
                tolog(job.pilotErrorDiag)
                ec = error.ERR_BADXML
                job.result[0] = "Badly formed XML (PoolFileCatalog.xml could not be parsed)"
                job.result[2] = ec
            if ec:
                runJob.failJob(0, ec, job, pilotErrorDiag=job.pilotErrorDiag)

            tolog("outputFileInfo=%s"%str(outputFileInfo))

            # in case the output files have been zipped, it is now safe to remove them and update the outFiles list
            # should only be executed if Archive_rf is skipped and pilot does all zipping
            if zip_map and False:
                tolog('Zip map cleanup pass #1 (skipped)')
                # job, outs, outputFileInfo = runJob.cleanupForZip(zip_map, archive_names, job, outs, outputFileInfo, datasetDict)
                tolog('Zip map cleanup pass #2')
                job.outFiles, job.destinationDblock, job.destinationDBlockToken, job.scopeOut, outs = \
                    job.removeInputFromOutputLists(job.inFiles, job.outFiles, job.destinationDblock, job.destinationDBlockToken, job.scopeOut, outs)
                tolog('Zip map cleanup pass #3')
                ec = pUtil.removeFiles(job.workdir, ins)

        # move output files from workdir to local DDM area
        finalUpdateDone = False
        if outs:

            # If clone job, make sure that stage-out should be performed
            if job.cloneJob == "storeonce":
                try:
                    message = downloadEventRanges(job.jobId, job.jobsetID, job.taskID, url=runJob.getPanDAServer())

                    # Create a list of event ranges from the downloaded message
                    event_ranges = runJob.extractEventRanges(message)

                    # Are there any event ranges?
                    if event_ranges == []:
                        tolog("!!WARNING!!2424!! This clone job was already executed and stored")
                        exitMsg = "Already executed/stored clone job"
                        res_tuple = (1, exitMsg)
                        res = (res_tuple[0], res_tuple[1], exitMsg)
                        job.result[0] = exitMsg
                        job.result[1] = 0 # transExitCode
                        job.result[2] = runJob.__error.ERR_EXECUTEDCLONEJOB # Pilot error code
                        job.pilotErrorDiag = exitMsg
                        runJob.failJob(0, ec, job, pilotErrorDiag=job.pilotErrorDiag)
                    else:
                        tolog("Ok to stage out clone job")
                except Exception, e:
                    tolog("!1WARNING!!2324!! Exception caught: %s" % (e))

            tolog("Setting stage-out state until all output files have been copied")
            job.setState(["stageout", 0, 0])
            rt = RunJobUtilities.updatePilotServer(job, runJob.getPilotServer(), runJob.getPilotPort())

            # Stage-out output files
            ec, job, rf, latereg = runJob.stageOut(job, jobSite, outs, analysisJob, dsname, datasetDict, outputFileInfo)
            # Error handling
            if job.result[0] == "finished" or ec == error.ERR_PUTFUNCNOCALL:
                rt = RunJobUtilities.updatePilotServer(job, runJob.getPilotServer(), runJob.getPilotPort(), final=True)
            else:
                rt = RunJobUtilities.updatePilotServer(job, runJob.getPilotServer(), runJob.getPilotPort(), final=True, latereg=latereg)
            if ec == error.ERR_NOSTORAGE:
                # Update the current file states for all files since nothing could be transferred
                updateFileStates(outs, runJob.getParentWorkDir(), job.jobId, mode="file_state", state="not_transferred")
                dumpFileStates(runJob.getParentWorkDir(), job.jobId)

            finalUpdateDone = True
            if ec != 0:
                runJob.sysExit(job, rf)

        # (Stage-out ends here) .......................................................................

        job.setState(["finished", 0, 0])
        if not finalUpdateDone:
            rt = RunJobUtilities.updatePilotServer(job, runJob.getPilotServer(), runJob.getPilotPort(), final=True)
        runJob.sysExit(job)

    except Exception, errorMsg:

        error = PilotErrors()

        if runJob.getGlobalPilotErrorDiag() != "":
            pilotErrorDiag = "Exception caught in RunJob: %s" % (runJob.getGlobalPilotErrorDiag())
        else:
            pilotErrorDiag = "Exception caught in RunJob: %s" % str(errorMsg)

        if 'format_exc' in traceback.__all__:
            pilotErrorDiag += ", " + traceback.format_exc()

        try:
            tolog("!!FAILED!!3001!! %s" % (pilotErrorDiag))
        except Exception, e:
            if len(pilotErrorDiag) > 10000:
                pilotErrorDiag = pilotErrorDiag[:10000]
                tolog("!!FAILED!!3001!! Truncated (%s): %s" % (e, pilotErrorDiag))
            else:
                pilotErrorDiag = "Exception caught in runJob: %s" % (e)
                tolog("!!FAILED!!3001!! %s" % (pilotErrorDiag))

#        # restore the proxy if necessary
#        if hP_ret:
#            rP_ret = proxyguard.restoreProxy()
#            if not rP_ret:
#                tolog("Warning: Problems with storage can occur since proxy could not be restored")
#            else:
#                hP_ret = False
#                tolog("ProxyGuard has finished successfully")

        tolog("sys.path=%s" % str(sys.path))
        cmd = "pwd;ls -lF %s;ls -lF;ls -lF .." % (runJob.getPilotInitDir())
        tolog("Executing command: %s" % (cmd))
        out = commands.getoutput(cmd)
        tolog("%s" % (out))

        job = Job.Job()
        job.setJobDef(newJobDef.job)
        job.pilotErrorDiag = pilotErrorDiag
        job.result[0] = "failed"
        if runJob.getGlobalErrorCode() != 0:
            job.result[2] = runJob.getGlobalErrorCode()
        else:
            job.result[2] = error.ERR_RUNJOBEXC
        tolog("Failing job with error code: %d" % (job.result[2]))
        # fail the job without calling sysExit/cleanup (will be called anyway)
        runJob.failJob(0, job.result[2], job, pilotErrorDiag=pilotErrorDiag, docleanup=False)

    # end of runJob
