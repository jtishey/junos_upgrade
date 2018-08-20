# SETTINGS VALUES:
# CODE_FOLDER    = SERVER DIRECTORY WHERE IMAGES ARE STORED
# CODE_LOG       = PATH AND FILENAME TO SAVE LOGS
# CODE_DEST      = PATH ON THE DEVICE TO SAVE IMAGES
# CODE_IMAGE64   = 64-BIT IMAGE NAME TO BE INSTALLED
# CODE_IMAGE32   = 32-BIT IMAGE NAME TO BE INSTALLED
# CODE_PRESERVE  = DIRECTORY FOR INTERMEDIATE IMAGE WHEN TWO-STAGE IS REQUIRED
# CODE_2STAGE64* = INTERMEDIATE IMAGE WHEN TWO-STAGE UPGRADE IS REQUIRED
# CODE_2STAGE32* = INTERMEDIATE IMAGE WHEN TWO-STAGE UPGRADE IS REQUIRED
# CODE_2STAGEFOR = RUNNING VERSIONS THAT NEED TWO STAGE UPGRADE
# CODE_JSU32*    = INSTALL A PATCH 32-BIT
# CODE_JSU64*    = INSTALL A PATCH 64-BIT
# (* = LEAVE EMPTY IF NOT REQUIRED)

# PRE_UPGRADE_CMDS  = COMMANDS TO BE APPLIED BEFORE STARTING THE UPGRADE
# POST_UPGRADE_CMDS = COMMANDS TO RESTORE CONFIG AFTER THE UPGRADE
#  (MX Platforms will be checked for network-services mode Enhanced-IP automatically)

CODE_FOLDER = '/opt/code/Juniper/Approved/MX/MX960/'
CODE_LOG = './junos_upgrade.log'
CODE_DEST = '/var/tmp/'
CODE_IMAGE64 = 'junos-install-mx-x86-64-16.1R6-S1.1.tgz'
CODE_IMAGE32 = 'junos-install-mx-x86-32-16.1R6-S1.1.tgz'
CODE_PRESERVE = '/var/preserve/'
CODE_2STAGE64 = 'jinstall-13.3R6-S1.6-domestic-signed.tgz'
CODE_2STAGE32 = 'jinstall64-13.3R6-S1.6-domestic-signed.tgz'
CODE_2STAGEFOR = '12'
CODE_JSU32 = 'jselective-update-J2-x86-32-16.1R6-S1-J2.tgz'
CODE_JSU64 = 'jselective-update-amd64-J2-x86-64-16.1R6-S1-J2.tgz'

CODE_FOLDER = '/home/john/Downloads/'
CODE_IMAGE64 = 'jinstall-ex-4200-15.1R7.8-domestic-signed.tgz'
CODE_IMAGE32 = 'jinstall-ex-4200-12.3R6.6-domestic-signed.tgz'
CODE_JSU32 = ''
CODE_JSU64 = ''

PRE_UPGRADE_CMDS = ['delete chassis redundancy failover',
                    'delete chassis redundancy graceful-switchover',
                    'delete routing-options nonstop-routing',
                    'delete protocols isis overload',
                    'set protocols isis overload advertise-high-metrics',
                    'delete protocols pim nonstop-routing disable',
                    ]

POST_UPGRADE_CMDS =  ['set routing-options nonstop-routing',
                      'set chassis redundancy failover on-loss-of-keepalives',
                      'set chassis redundancy graceful-switchover',
                      'delete protocols isis overload',
                      'set protocols isis overload timeout 600',
                      'set protocols isis overload advertise-high-metrics',
                      'set protocols pim nonstop-routing disable',
                    ]
PRE_UPGRADE_CMDS = ''
POST_UPGRADE_CMDS =  ''