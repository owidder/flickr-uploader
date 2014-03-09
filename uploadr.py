#!/usr/local/bin/python

"""

    flickr-uploader designed for Synology Devices
    Upload a directory of media to Flickr to use as a backup to your local storage.

    Features:

    -Uploads both images and movies (JPG, PNG, GIF, AVI, MOV files)
    -Stores image information locally using a simple SQLite database
    -Automatically creates "Sets" based on the folder name the media is in
    -Ignores ".picasabackup" directory
    -Automatically removes images from Flickr when they are removed from your local hard drive

    Requirements:

    -Python 2.7+
    -File write access (for the token and local database)
    -Flickr API key (free)

    Setup:

    Go to http://www.flickr.com/services/apps/create/apply and apply for an API key Edit the following variables near the top in the script:

    FILES_DIR = "files/"
    TOKEN_DIR = "~/.flickr"
    FLICKR = { "title" : "", "description" : "", "tags" : "auto-upload", "is_public" : "0", "is_friend" : "0", "is_family" : "1" }
    SLEEP_TIME = 1 * 60
    DRIP_TIME = 1 * 60
    DB_PATH = os.path.join(FILES_DIR, "fickerdb")
    FLICKR["api_key"] = ""
    FLICKR["secret"] = ""
    Place the file uploadr.py in any directory and run:

    $ ./uploadr.py

    It will crawl through all the files from the FILES_DIR directory and begin the upload process.

    Upload files placed within a directory to your Flickr account.

   Inspired by:
        http://micampe.it/things/flickruploadr
        https://github.com/joelmx/flickrUploadr/blob/master/python3/uploadr.py

   Usage:

   cron entry (runs at the top of every hour )
   0  *  *   *   * /full/path/to/uploadr.py > /dev/null 2>&1

   This code has been updated to use the new Auth API from flickr.

   You may use this code however you see fit in any form whatsoever.


"""
import sys
if sys.version_info < (2,7):
  sys.stderr.write("This script requires Python 2.7 or newer.\n")
  sys.stderr.write("Current version: " + sys.version + "\n")
  sys.stderr.flush()
  sys.exit(1)

import argparse
import hashlib
import mimetools
import mimetypes
import os
import shelve
import string
import time
import urllib
import urllib2
import webbrowser
import sqlite3 as lite
import pprint
import json
from xml.dom.minidom import parse
import hashlib
import fcntl
import errno
from sys import stdout
import itertools

#
##
##  Items you will want to change
##

#
# Location to scan for new files
#
FILES_DIR = os.environ['FLICKR_UPLOADR_FILES_DIR']
if not FILES_DIR.endswith('/'):
    FILES_DIR = FILES_DIR + '/'

#
# Location to store the token
#
TOKEN_DIR = os.environ['FLICKR_UPLOADR_TOKEN_DIR']
#
#   Flickr settings
#
FLICKR = {
        "title"                 : "",
        "description"           : "",
        "tags"                  : "auto-upload",
        "is_public"             : "0",
        "is_friend"             : "0",
        "is_family"             : "0"
        }
#
#   How often to check for new files to upload (in seconds)
#
SLEEP_TIME = 1 * 60
#
#   Only with --drip-feed option:
#     How often to wait between uploading individual files (in seconds)
#
DRIP_TIME = 1 * 60
#
#   File we keep the history of uploaded files in.
#
DB_PATH = os.path.join(FILES_DIR, "fickerdb")
#
#   List of folder names you don't want to parse
#
EXCLUDED_FOLDERS = ["@eaDir","#recycle",".picasaoriginals","_ExcludeSync","Corel Auto-Preserve","Originals","Automatisch beibehalten von Corel"]
#
#   List of file extensions you agree to upload
#
ALLOWED_EXT = ["jpg","png"]
#
#   Files greater than this value won't be uploaded (1Mo = 1000000)
#
FILE_MAX_SIZE = 50000000
#
#   Do you want to verify each time if already uploaded files have been changed?
#
MANAGE_CHANGES = True
#
#   Your own API key and secret message
#
FLICKR["api_key"] = os.environ['FLICKR_API_KEY']
FLICKR["secret"] = os.environ['FLICKR_SECRET']

##
##  You shouldn't need to modify anything below here
##

class APIConstants:
    """ APIConstants class
    """

    base = "http://api.flickr.com/services/"
    rest   = base + "rest/"
    auth   = base + "auth/"
    upload = base + "upload/"
    replace = base + "replace/"

    def __init__( self ):
       """ Constructor
       """
       pass

api = APIConstants()

class Uploadr:
    """ Uploadr class
    """

    token = None
    perms = ""
    TOKEN_FILE = os.path.join(TOKEN_DIR, "flickrToken")

    def __init__( self ):
        """ Constructor
        """
        self.token = self.getCachedToken()



    def signCall( self, data):
        """
        Signs args via md5 per http://www.flickr.com/services/api/auth.spec.html (Section 8)
        """
        keys = data.keys()
        keys.sort()
        foo = ""
        for a in keys:
            foo += (a + data[a])

        f = FLICKR[ "secret" ] + "api_key" + FLICKR[ "api_key" ] + foo
        #f = "api_key" + FLICKR[ "api_key" ] + foo

        return hashlib.md5( f ).hexdigest()

    def urlGen( self , base,data, sig ):
        """ urlGen
        """
        data['api_key'] = FLICKR[ "api_key" ]
        data['api_sig'] = sig
        encoded_url = base + "?" + urllib.urlencode( data )
        return encoded_url


    def authenticate( self ):
        """ Authenticate user so we can upload files
        """

        print("Getting new token")
        self.getFrob()
        self.getAuthKey()
        self.getToken()
        self.cacheToken()

    def getFrob( self ):
        """
        flickr.auth.getFrob

        Returns a frob to be used during authentication. This method call must be
        signed.

        This method does not require authentication.
        Arguments

        "api_key" (Required)
        Your API application key. See here for more details.
        """

        d = {
            "method"          : "flickr.auth.getFrob",
            "format"          : "json",
            "nojsoncallback"    : "1"
            }
        sig = self.signCall( d )
        url = self.urlGen( api.rest, d, sig )
        try:
            response = self.getResponse( url )
            if ( self.isGood( response ) ):
                FLICKR[ "frob" ] = str(response["frob"]["_content"])
            else:
                self.reportError( response )
        except:
            print("Error: cannot get frob:" + str( sys.exc_info() ))

    def getAuthKey( self ):
        """
        Checks to see if the user has authenticated this application
        """
        d =  {
            "frob"            : FLICKR[ "frob" ],
            "perms"           : "delete"
            }
        sig = self.signCall( d )
        url = self.urlGen( api.auth, d, sig )
        ans = ""
        try:
            webbrowser.open( url )
            print("Copy-paste following URL into a web browser and follow instructions:")
            print(url)
            ans = raw_input("Have you authenticated this application? (Y/N): ")
        except:
            print(str(sys.exc_info()))
        if ( ans.lower() == "n" ):
            print("You need to allow this program to access your Flickr site.")
            print("Copy-paste following URL into a web browser and follow instructions:")
            print(url)
            print("After you have allowed access restart uploadr.py")
            sys.exit()

    def getToken( self ):
        """
        http://www.flickr.com/services/api/flickr.auth.getToken.html

        flickr.auth.getToken

        Returns the auth token for the given frob, if one has been attached. This method call must be signed.
        Authentication

        This method does not require authentication.
        Arguments

        NTC: We need to store the token in a file so we can get it and then check it insted of
        getting a new on all the time.

        "api_key" (Required)
           Your API application key. See here for more details.
        frob (Required)
           The frob to check.
        """

        d = {
            "method"          : "flickr.auth.getToken",
            "frob"            : str(FLICKR[ "frob" ]),
            "format"          : "json",
            "nojsoncallback"    : "1"
        }
        sig = self.signCall( d )
        url = self.urlGen( api.rest, d, sig )
        try:
            res = self.getResponse( url )
            if ( self.isGood( res ) ):
                self.token = str(res['auth']['token']['_content'])
                self.perms = str(res['auth']['perms']['_content'])
                self.cacheToken()
            else :
                self.reportError( res )
        except:
            print(str(sys.exc_info()))

    def getCachedToken( self ):
        """
        Attempts to get the flickr token from disk.
       """
        if ( os.path.exists( self.TOKEN_FILE )):
            return open( self.TOKEN_FILE ).read()
        else :
            return None



    def cacheToken( self ):
        """ cacheToken
        """

        try:
            open( self.TOKEN_FILE , "w").write( str(self.token) )
        except:
            print("Issue writing token to local cache ", str(sys.exc_info()))

    def checkToken( self ):
        """
        flickr.auth.checkToken

        Returns the credentials attached to an authentication token.
        Authentication

        This method does not require authentication.
        Arguments

        "api_key" (Required)
            Your API application key. See here for more details.
        auth_token (Required)
            The authentication token to check.
        """

        if ( self.token == None ):
            return False
        else :
            d = {
                "auth_token"      :  str(self.token) ,
                "method"          :  "flickr.auth.checkToken",
                "format"          : "json",
                "nojsoncallback"  : "1"
            }
            sig = self.signCall( d )

            url = self.urlGen( api.rest, d, sig )
            try:
                res = self.getResponse( url )
                if ( self.isGood( res ) ):
                    self.token = res['auth']['token']['_content']
                    self.perms = res['auth']['perms']['_content']
                    return True
                else :
                    self.reportError( res )
            except:
                print(str(sys.exc_info()))
            return False

    def upload( self ):
        """ upload
        """

        print("*****Uploading files*****")

        allSets = self.readAllSets();

        termCtr = 0

        for dirpath, dirnames, filenames in os.walk( FILES_DIR, followlinks=True):
            if ('@' in dirpath) or ('_f-' in dirpath):
                # print "--- Skipped: " + dirpath
                continue

            startindex = FILES_DIR.__len__()
            relpath = dirpath[startindex:]
            parts = relpath.split('/')

            setname = "-".join(parts)
            if (setname.__len__() > 1) and (filenames.__len__() > 0):
                for filename in filenames:
                    ext = filename.lower().split(".")[-1]
                    if (not filename.startswith("_f-")) and (ext in ALLOWED_EXT):
                        if not self.doesSetExist(setname, allSets):
                            print "Create set: " + setname
                        print "Uplaod: " + dirpath + '/' + filename
                        termCtr = termCtr + 1
                        if termCtr > 0:
                            return

            print "*****************"

            """
            for curr_dir in EXCLUDED_FOLDERS:
                if curr_dir in dirnames:
                    dirnames.remove(curr_dir)
            for f in filenames :
                ext = f.lower().split(".")[-1]
                if (not f.startswith("_f-")) and (not dirpath.startswith("_f-")) and (ext in ALLOWED_EXT):
                    fileSize = os.path.getsize( dirpath + "/" + f )
                    if (fileSize < FILE_MAX_SIZE):
                        print(dirpath + "/" + f)
            """

        """
        allMedia = self.grabNewFiles()
        print("Found " + str(len(allMedia)) + " files")
        coun = 0;
        for i, file in enumerate( allMedia ):
            success = self.uploadFile( file )
            if args.drip_feed and success and i != len( newFiles )-1:
                print("Waiting " + str(DRIP_TIME) + " seconds before next upload")
                time.sleep( DRIP_TIME )
            coun = coun + 1;
            if (coun%100 == 0):
                print("   " + str(coun) + " files processed (uploaded or md5ed)")
        if (coun%100 > 0):
            print("   " + str(coun) + " files processed (uploaded or md5ed)")
        print("*****Completed uploading files*****")
        """

    def uploadFile( self, file ):
        """ uploadFile
        """

        success = False
        print("Uploading " + file + "...")
        head, setName = os.path.split(os.path.dirname(file))
        try:
            photo = ('photo', file, open(file,'rb').read())
            if args.title: # Replace
                FLICKR["title"] = args.title
            if args.description: # Replace
                FLICKR["description"] = args.description
            if args.tags: # Append
                FLICKR["tags"] += " " + args.tags + " "
            d = {
                "auth_token"    : str(self.token),
                "perms"         : str(self.perms),
                "title"         : str( FLICKR["title"] ),
                "description"   : str( FLICKR["description"] ),
                "tags"          : str( FLICKR["tags"] + "," + setName ),
                "is_public"     : str( FLICKR["is_public"] ),
                "is_friend"     : str( FLICKR["is_friend"] ),
                "is_family"     : str( FLICKR["is_family"] )
            }
            sig = self.signCall( d )
            d[ "api_sig" ] = sig
            d[ "api_key" ] = FLICKR[ "api_key" ]
            url = self.build_request(api.upload, d, (photo,))
            res = parse(urllib2.urlopen( url ))
            if ( not res == "" and res.documentElement.attributes['stat'].value == "ok" ):
                print("Successfully uploaded the file: " + file)
                # Add to set
                cur.execute('INSERT INTO files (files_id, path, md5, tagged) VALUES (?, ?, ?, 1)',(int(str(res.getElementsByTagName('photoid')[0].firstChild.nodeValue)), file, self.md5Checksum(file)))
                success = True
            else :
                print("A problem occurred while attempting to upload the file: " + file)
                try:
                    print("Error: " + str( res.toxml() ))
                except:
                    print("Error: " + str( res.toxml() ))
        except:
            print(str(sys.exc_info()))

        return success

    def build_request(self, theurl, fields, files, txheaders=None):
        """
        build_request/encode_multipart_formdata code is from www.voidspace.org.uk/atlantibots/pythonutils.html

        Given the fields to set and the files to encode it returns a fully formed urllib2.Request object.
        You can optionally pass in additional headers to encode into the opject. (Content-type and Content-length will be overridden if they are set).
        fields is a sequence of (name, value) elements for regular form fields - or a dictionary.
        files is a sequence of (name, filename, value) elements for data to be uploaded as files.
        """

        content_type, body = self.encode_multipart_formdata(fields, files)
        if not txheaders: txheaders = {}
        txheaders['Content-type'] = content_type
        txheaders['Content-length'] = str(len(body))

        return urllib2.Request(theurl, body, txheaders)

    def encode_multipart_formdata(self,fields, files, BOUNDARY = '-----'+mimetools.choose_boundary()+'-----'):
        """ Encodes fields and files for uploading.
        fields is a sequence of (name, value) elements for regular form fields - or a dictionary.
        files is a sequence of (name, filename, value) elements for data to be uploaded as files.
        Return (content_type, body) ready for urllib2.Request instance
        You can optionally pass in a boundary string to use or we'll let mimetools provide one.
        """

        CRLF = '\r\n'
        L = []
        if isinstance(fields, dict):
            fields = fields.items()
        for (key, value) in fields:
            L.append('--' + BOUNDARY)
            L.append('Content-Disposition: form-data; name="%s"' % key)
            L.append('')
            L.append(value)
        for (key, filename, value) in files:
            filetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            L.append('--' + BOUNDARY)
            L.append('Content-Disposition: form-data; name="%s"; filename="%s"' % (key, filename))
            L.append('Content-Type: %s' % filetype)
            L.append('')
            L.append(value)
        L.append('--' + BOUNDARY + '--')
        L.append('')
        body = CRLF.join(L)
        content_type = 'multipart/form-data; boundary=%s' % BOUNDARY        # XXX what if no files are encoded
        return content_type, body

    def isGood( self, res ):
        """ isGood
        """

        if ( not res == "" and res['stat'] == "ok" ):
            return True
        else :
            return False

    def reportError( self, res ):
        """ reportError
        """

        try:
            print("Error: " + str( res['code'] + " " + res['message'] ))
        except:
            print("Error: " + str( res ))

    def getResponse( self, url ):
        """
        Send the url and get a response.  Let errors float up
        """

        try:
            res = urllib2.urlopen( url ).read()
        except urllib2.HTTPError as e:
            print(e.code)
        except urllib2.URLError as e:
            print(e.args)
        return json.loads(res)

    def run( self ):
        """ run
        """

        while ( True ):
            self.upload()
            print("Last check: " + str( time.asctime(time.localtime())))
            time.sleep( SLEEP_TIME )

    def addFileToSet( self, setId, file, cur):
        try:
            d = {
                "auth_token"          : str(self.token),
                "perms"               : str(self.perms),
                "format"              : "json",
                "nojsoncallback"      : "1",
                "method"              : "flickr.photosets.addPhoto",
                "photoset_id"         : str( setId ),
                "photo_id"            : str( file[0] )
            }
            sig = self.signCall( d )
            url = self.urlGen( api.rest, d, sig )

            res = self.getResponse( url )
            if ( self.isGood( res ) ):

                print("Successfully added file " + str(file[1]) + " to its set.")

                cur.execute("UPDATE files SET set_id = ? WHERE files_id = ?", (setId, file[0]))

            else :
                if ( res['code'] == 1 ) :
                    print("Photoset not found, creating new set...")
                    head, setName = os.path.split(os.path.dirname(file[1]))
                    con = lite.connect(DB_PATH)
                    con.text_factory = str
                    self.createSet( setName, file[0], cur, con)
                else :
                    self.reportError( res )
        except:
            print(str(sys.exc_info()))

    def createSet( self, setName, primaryPhotoId):
        print("Creating new set: " + str(setName))

        try:
            d = {
                "auth_token"          : str(self.token),
                "perms"               : str(self.perms),
                "format"              : "json",
                "nojsoncallback"      : "1",
                "method"              : "flickr.photosets.create",
                "primary_photo_id"    : str( primaryPhotoId ),
                "title"               : setName

            }


            sig = self.signCall( d )

            url = self.urlGen( api.rest, d, sig )
            res = self.getResponse( url )
            if ( self.isGood( res ) ):
                return res["photoset"]["id"]
            else :
                print(d)
                self.reportError( res )
        except:
            print(str(sys.exc_info()))
        return False

    def md5Checksum(self, filePath):
        with open(filePath, 'rb') as fh:
            m = hashlib.md5()
            while True:
                data = fh.read(8192)
                if not data:
                    break
                m.update(data)
            return m.hexdigest()

    def addTagsToUploadedPhotos ( self ) :
        print('*****Adding tags to existing photos*****')

        con = lite.connect(DB_PATH)
        con.text_factory = str

        with con:

            cur = con.cursor()
            cur.execute("SELECT files_id, path, set_id, tagged FROM files")

            files = cur.fetchall()

            for row in files:
                if(row[3] != 1) :
                    head, setName = os.path.split(os.path.dirname(row[1]))

                    status = self.addTagToPhoto(row, setName, cur, con)

                    if status == False:
                        print("Error: cannot add tag to file: " + file[1])

        print('*****Completed adding tags*****')

    def addTagToPhoto(self, file, tagName, cur, con) :
        print("Adding tag " + tagName + " to photo: " + str(file[1]) + " (" + str(file[0]) + ")")

        try:
            d = {
                "auth_token"          : str(self.token),
                "perms"               : str(self.perms),
                "format"              : "json",
                "nojsoncallback"      : "1",
                "method"              : "flickr.photos.addTags",
                "photo_id"          : str( file[0] ),
                "tags"               : tagName
            }
            sig = self.signCall( d )
            url = self.urlGen( api.rest, d, sig )

            res = self.getResponse( url )
            if ( self.isGood( res ) ):
                cur.execute("UPDATE files SET tagged=? WHERE files_id=?", (1, file[0]))
                con.commit()
                return True
            else :
                print(d)
                self.reportError( res )
        except:
            print(str(sys.exc_info()))
        return False

    # Display Sets
    def displaySets( self ) :
        con = lite.connect(DB_PATH)
        con.text_factory = str
        with con:
            cur = con.cursor()
            cur.execute("SELECT set_id, name FROM sets")
            allsets = cur.fetchall()
            for row in allsets:
                print("Set: " + str(row[0]) + "(" + row[1] + ")")

    """
    Print all set names from the result
    of 'flickr.photosets.getList'
    """
    def printAllSetNames(self, allSetsJson):
        for s in allSetsJson['photosets']['photoset']:
            print s['title']['_content']

    """
    Helper method
    Return True if if 'setname' exists in the JSON structure 'allSetsJson'
    as returned from 'flickr.photosets.getList'
    """
    def doesSetExist(self, setname, allSetsJson):
        itExists = False

        for s in allSetsJson['photosets']['photoset']:
            if s['title']['_content'] == setname:
                itExists = True
                break

        return itExists

    # Get sets from Flickr
    def readAllSets(self):
        """ 
        Read all sets from Flickr
        """

        try:
            d = {
                "auth_token"          : str(self.token),
                "perms"               : str(self.perms),
                "format"              : "json",
                "nojsoncallback"      : "1",
                "method"              : "flickr.photosets.getList"
            }
            url = self.urlGen(api.rest, d, self.signCall(d))
            allSets = self.getResponse(url)
        except:
            print(str(sys.exc_info()))

        return allSets

####################################################################
####################################################################
####################################################################

print("--------- Start time: " + time.strftime("%c") + " ---------");
if __name__ == "__main__":
    # Ensure that only once instance of this script is running
    f = open ('lock', 'w')
    try: fcntl.lockf (f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError as e:
        if e.errno == errno.EAGAIN:
            sys.stderr.write('[%s] Script already running.\n' % time.strftime ('%c') )
            sys.exit(-1)
        raise
    parser = argparse.ArgumentParser(description='Upload files to Flickr.')
    parser.add_argument('-d', '--daemon', action='store_true',
        help='Run forever as a daemon')
    parser.add_argument('-i', '--title',       action='store',
        help='Title for uploaded files')
    parser.add_argument('-e', '--description', action='store',
        help='Description for uploaded files')
    parser.add_argument('-t', '--tags',        action='store',
        help='Space-separated tags for uploaded files')
    parser.add_argument('-r', '--drip-feed',   action='store_true',
        help='Wait a bit between uploading individual files')
    args = parser.parse_args()

    flick = Uploadr()

    if FILES_DIR == "":
        print("Please configure the name of the folder in the script with media available to sync with Flickr.")
        sys.exit()

    if FLICKR["api_key"] == "" or FLICKR["secret"] == "":
        print("Please enter an API key and secret in the script file (see README).")
        sys.exit()

    if args.daemon:
        #flick.run()
        dummy = 1
    else:
        if ( not flick.checkToken() ):
            flick.authenticate()

        #allSets = flick.readAllSets()
        #flick.printAllSetNames(allSets)

        flick.upload()

        """
        flick.addTagsToUploadedPhotos()
        """
print("--------- End time: " + time.strftime("%c") + " ---------");
