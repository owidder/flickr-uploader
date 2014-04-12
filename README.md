Derivation from the original script on the master branch

* No DB
* No Sync
* Upload all PNG and JPG not beginning with '_f-' (and no folder in the path begins with '_f-')
* Rename the file after upload to: _f-&lt;original file name w/o extension>-&lt;flickr-id>.&lt;extension>
* When a file fails to uplaod, a '_e-' is prepended to the filename
* Files beginning with '_e-_e-' (i.e. failed twice) are not uploaded

