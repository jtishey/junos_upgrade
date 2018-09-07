### Junos Upgrade

This script is designed to upgrade JUNOS routers.

Running this script will be service impacting.


John Tishey - 2018





## Sample Output 1 - EX4200 upgrade
```john➜~» scripts/python/junos_upgrade/junos_upgrade.py -d 172.16.212.21 -c ./config.yml -y                            [1:54:20]
Information logged in 172.16.212.21_upgrade.log
Connecting to 172.16.212.21...
172.16.212.21 EX4200-24T
------------------------
              RE0  
Mastership: master
Status:     OK
Model:      EX4200-24T, 8 POE
Version:    12.3R12.4

Checking for redundant routing-engines...
Redundant RE's not found...
Checking for 32 or 64-bit code...
Using 32-bit Image...
Checking for image on the active RE...
Requesting system snapshot on RE0...
Error taking snapshot... Please check device logs
No pre-upgrade commands in CONFIG file
------------------------WARNING-----------------------------
Ready to upgrade, THIS WILL BE SERVICE IMPACTING!!!        
-----------------------------------------------------------
Upgrading device... Please Wait...
-----------------START PKG ADD OUTPUT-----------------


[Sep  5 01:31:20]: Checking pending install on fpc0
None


fpc0:
Verify the signature of the new package
Verified jinstall-ex-4200-15.1R7.8-domestic.tgz signed by PackageProductionRSA_2018
WARNING: A reboot is required to install the software
WARNING:     Use the 'request system reboot' command immediately


Rebooting fpc0

------------------END PKG ADD OUTPUT------------------
Rebooting, please wait...
Package /var/tmp/jinstall-ex-4200-15.1R7.8-domestic-signed.tgz took 0:12:13
Checking for core dumps...
SW Version: 15.1R7.8
Restoring configruation...
No post-upgrade commands in CONFIG file
Requesting system snapshot on RE0...
Error taking snapshot... Please check device logs
------------------------
|       RESULTS        |
------------------------
172.16.212.21 EX4200-24T
------------------------
              RE0  
Mastership: master
Status:     Absent
Model:      EX4200-24T, 8 POE
Version:    15.1R7.8

Checking for redundant routing-engines...
Redundant RE's not found...
Disconnecting from 172.16.212.21...
```


