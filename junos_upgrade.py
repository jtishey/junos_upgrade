#!/opt/ipeng/ENV/bin/python3
"""
    This script is designed to upgrade JUNOS routers.
    Running this script will be service impacting.
    John Tishey - 2018
"""

import os, sys, logging, time
from jnpr.junos import Device
from jnpr.junos.utils.scp import SCP
from jnpr.junos.utils.config import Config
from jnpr.junos.exception import ConnectError
import argparse
import xmltodict
from lxml import etree
import json
import CONFIG


class RunUpgrade(object):
    def __init__(self):
        self.arch = ''
        self.host = ''
        self.force = False
        self.yes_all = False
        self.username = 'guest'
        self.password = 'password'
        self.set_enhanced_ip = False
        self.pim_nonstop = False
        self.two_stage = False


    def get_arguments(self):
        """ Handle input from CLI """
        p = argparse.ArgumentParser(
            description='Parse and compare before/after baseline files.')
        p.add_argument('-d', '--device', help='Specify an IP or hostname to upgrade', required=True)
        p.add_argument('-f', '--force', action='count', default=0, 
                        help='Use "force" option on all package adds (DANGER!)', required=False)
        p.add_argument('-y', '--yes_all', action='count', default=0,
                        help='Answer "y" to all questions during the upgrade (DANGER!)', required=False)
        args = vars(p.parse_args())
        self.host = args['device']
        if args['force']:
            self.force - True
        if args['yes_all']:
            self.yes_all = True


    def initial_setup(self):
        """ Setup logging and check for the image on the server """
        logging.basicConfig(filename=CONFIG.CODE_LOG, level=logging.WARN,
                            format='%(asctime)s:%(name)s: %(message)s')
        logging.getLogger().name = self.host
        logging.getLogger().addHandler(logging.StreamHandler())
        logging.info('Information logged in {0}'.format(CONFIG.CODE_LOG))

        # verify package exists on local server
        if not (os.path.isfile(CONFIG.CODE_FOLDER + CONFIG.CODE_IMAGE64)):
            msg = 'Software package does not exist: {0}. '.format(
                                CONFIG.CODE_FOLDER + CONFIG.CODE_IMAGE64)
            logging.error(msg)
            sys.exit()


    def open_connection(self):
        """ Open a NETCONF connection to the device """
        try:
            logging.warn('Connecting to ' + self.host + '...')
            self.dev = Device(host=self.host,
                              user=self.username,
                              password=self.password,
                              gather_facts=True)
            self.dev.open()
        except ConnectError as e:
            logging.error('Cannot connect to device: {0}'.format(e))
            exit(1)


    def collect_re_info(self):
        """ Print info on each RE: """
        if self.dev.facts['RE0']:
            logging.warn('' + self.host + ' ' + self.dev.facts['model'])
            logging.warn('-' * 24)
            if self.dev.facts['version_RE0']:
                logging.warn('            RE0   \t   RE1')
                logging.warn('Mastership: ' + \
                                 self.dev.facts['RE0']['mastership_state'] + '\t' + \
                                 self.dev.facts['RE1']['mastership_state'] + '')
                logging.warn('Status:     ' + \
                                 self.dev.facts['RE0']['status'] + '\t\t' + \
                                 self.dev.facts['RE1']['status'] + '')
                logging.warn('Model:      ' + \
                                 self.dev.facts['RE0']['model'] + '\t' + \
                                 self.dev.facts['RE1']['model'] + '')
                logging.warn('Version:    ' + \
                                 self.dev.facts['version_RE0'] + '\t' + \
                                 self.dev.facts['version_RE1'] + '')
            else:
                logging.warn('              RE0  ')
                logging.warn('Mastership: ' + \
                                 self.dev.facts['RE0']['mastership_state'] + '')
                logging.warn('Status:     ' + \
                                 self.dev.facts['RE0']['status'] + '')
                logging.warn('Model:      ' + \
                                 self.dev.facts['RE0']['model'] + '')
                logging.warn('Version:    ' + \
                                 self.dev.facts['version'] + '')
            logging.warn("")
    
            # Check for redundant REs
            logging.warn('Checking for redundant routing-engines...')
            if not self.dev.facts['2RE']:
                if not self.yes_all:
                    re_stop = input("Redundant RE's not found, Continue? (y/n): ")
                    if re_stop.lower() != 'y':
                        self.dev.close()
                        exit()
                else:
                    logging.warn("Redundant RE's not found...")

      
    def copy_image(self, source, dest):
        """ Copy files via SCP """
        logging.warn("Image not found on active RE, copying now...")
        try:
            with SCP(self.dev, progress=True) as scp:
                logging.warn("Copying image to " + dest + "...")
                scp.put(source, remote_path=dest)
        except FileNotFoundError as e:
            logging.warn(str(e))
            logging.warn('ERROR: Local file "' + source + '" not found')
            self.dev.close()
            exit()


    def image_check(self):
        """ Check to make sure needed files are on the device and copy if needed,
            Currently only able to copy to the active RE 
        """
        # List of 64-bit capable RE's:
        RE_64 = ['RE-S-1800x2-8G',
                 'RE-S-1800x2-16G',
                 'RE-S-1800x4-8G',
                 'RE-S-1800x4-16G']
        
        if self.dev.facts['RE0']['model'] in RE_64:
            self.arch = '64-bit'
        else:
            # Determine 32-bit or 64-bit:
            logging.warn('Checking for 32 or 64-bit code...')
            ver = xmltodict.parse(etree.tostring(
                   self.dev.rpc.get_software_information(detail=True)))
            version_info = json.dumps(ver)
            if '64-bit' in version_info:
                self.arch = '64-bit'
            elif '32-bit' in version_info:
                self.arch = '32-bit'
            else:
                logging.warn("1. 32-bit Image - " + str(CONFIG.CODE_IMAGE32))
                logging.warn("2. 64-bit Image - " + str(CONFIG.CODE_IMAGE64))
                image_type = input("Select Image Type (1/2): ")
                if image_type == '1':
                    self.arch = '32-bit'
                    logging.warn('32-bit Code Selected')
                elif image_type == '2':
                    self.arch = '64-bit'
                    logging.warn('64-bit Code Selected')
                else:
                    logging.warn("Please enter only 1 or 2")
                    self.image_check()
                    return

        # Are we doing a two-stage upgrade? (Reqd for >3 major version change)
        if CONFIG.CODE_2STAGE32 or CONFIG.CODE_2STAGE64:
            if self.dev.facts['version'][:2] == CONFIG.CODE_2STAGEFOR:
                logging.warn('Two-Stage Upgrade will be performed...')
                self.two_stage = True
        
        # Define all the file names / paths
        if self.arch == '32-bit':
            source = CONFIG.CODE_FOLDER + CONFIG.CODE_IMAGE32
            source_2stg = CONFIG.CODE_FOLDER + CONFIG.CODE_2STAGE32
            source_jsu = CONFIG.CODE_FOLDER + CONFIG.CODE_JSU32
            if self.two_stage:
                dest = CONFIG.CODE_PRESERVE + CONFIG.CODE_IMAGE32
                dest_2stg = CONFIG.CODE_DEST + CONFIG.CODE_2STAGE32
                dest_jsu = CONFIG.CODE_PRESERVE + CONFIG.CODE_JSU32
            else:
                dest = CONFIG.CODE_DEST + CONFIG.CODE_IMAGE32
                dest_jsu = CONFIG.CODE_DEST + CONFIG.CODE_JSU32            
        elif self.arch == '64-bit':
            source = CONFIG.CODE_FOLDER + CONFIG.CODE_IMAGE64
            source_2stg = CONFIG.CODE_FOLDER + CONFIG.CODE_2STAGE64
            source_jsu = CONFIG.CODE_FOLDER + CONFIG.CODE_JSU64
            if self.two_stage:
                dest = CONFIG.CODE_PRESERVE + CONFIG.CODE_IMAGE64
                dest_2stg = CONFIG.CODE_DEST + CONFIG.CODE_2STAGE64
                dest_jsu = CONFIG.CODE_PRESERVE + CONFIG.CODE_JSU64
            else:
                dest = CONFIG.CODE_DEST + CONFIG.CODE_IMAGE64
                dest_jsu = CONFIG.CODE_DEST + CONFIG.CODE_JSU64     

        # Check for final software image on the device
        logging.warn('Checking for image on the active RE...')
        img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=dest)))
        img_output = json.dumps(img)
        if 'No such file' in img_output:
            self.copy_image(source, dest)

        # If dual RE - Check backup RE too
        if self.dev.facts['2RE']:
            if self.dev.facts['master'] == 'RE0':
                backup_RE = 're1:/'
            else:
                backup_RE = 're0:/'
            logging.warn('Checking for image on the backup RE...')
            img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=backup_RE + dest)))
            img_output = json.dumps(img)
            if 'No such file' in img_output:
                msg = 'file copy ' + dest + ' ' + backup_RE + dest
                logging.warn('ERROR: Copy the image to the backup RE, then re-run script')
                logging.warn('CMD  : ' + msg)
                self.dev.close()
                exit()

        # If 2 stage upgrade, look for intermediate image
        if self.two_stage:
            logging.warn('Checking for 2-stage image on the active RE...')
            img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=dest_2stg)))                
            img_output = json.dumps(img)
            if 'No such file' in img_output:
                self.copy_image(source_2stg, dest_2stg)

            # Check for intermediate image file on backup RE
            if self.dev.facts['2RE']:
                logging.warn('Checking for 2-stage image on the backup RE...')
                img = xmltodict.parse(etree.tostring(
                        self.dev.rpc.file_list(path=backup_RE + dest_2stg)))
                img_output = json.dumps(img)
                if 'No such file' in img_output:
                    msg = 'file copy ' + dest_2stg + ' ' + backup_RE + dest_2stg
                    logging.warn('ERROR: Copy the intermediate image to the backup RE, then re-run script')
                    logging.warn('CMD  : ' + msg)
                    self.dev.close()
                    exit()

        # Check if JSU Install is requested
        if CONFIG.CODE_JSU32 or CONFIG.CODE_JSU64:
            # Check for the JSU on the active RE
            logging.warn('Checking for JSU on the active RE...')
            img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=dest_jsu)))                
            img_output = json.dumps(img)
            if 'No such file' in img_output:
                self.copy_image(source_jsu, dest_jsu)

            # Check for the JSU on the backup RE
            if self.dev.facts['2RE']:
                logging.warn('Checking for JSU on the backup RE...')
                img = xmltodict.parse(etree.tostring(
                        self.dev.rpc.file_list(path=backup_RE + dest_jsu)))
                img_output = json.dumps(img)
                if 'No such file' in img_output:
                    msg = 'file copy ' + dest_jsu + ' ' + backup_RE + dest_jsu
                    logging.warn('ERROR: Copy the JSU to the backup RE, then re-run script')
                    logging.warn('CMD  : ' + msg)
                    self.dev.close()
                    exit()


    def system_snapshot(self):
        """ Performs [request system snapshot] on the device """
        logging.warn('Requesting system snapshot...')
        self.dev.rpc.request_snapshot()


    def remove_traffic(self):
        """ Execute the PRE_UPGRADE_CMDS from the CONFIG.py file to remove traffic """
        config_cmds = CONFIG.PRE_UPGRADE_CMDS
        if type(config_cmds) != 'list':
            logging.warn("CONFIG.py Error: PRE_UPGRADE_CMDS in CONFIG.py must be a list")
            logging.warn("Ex. ['set something', 'set something else']")
            logging.warn("Please correct and re-run the script")
            self.dev.close()
            exit()
        
        # Network Service check on MX Platform
        if self.dev.facts['model'][:2] == 'MX':
            net_mode = xmltodict.parse(etree.tostring(
                        self.dev.rpc.network_services()))
            cur_mode = net_mode['network-services']['network-services-information']['name']
            if cur_mode != 'Enhanced-IP':
                logging.warn('Network Services mode is ' + cur_mode + '')
                if not self.yes_all:
                    cont = input('Change Network Services Mode to Enhanced-IP? (y/n): ')
                    if cont.lower() == 'y':
                        # Set a flag to recheck at the end and reboot if needed:
                        self.set_enhanced_ip = True
                else:
                    self.set_enhanced_ip = True
        
        # PIM nonstop-routing must be removed if it's there to deactivate GRES
        pim = self.dev.rpc.get_config(filter_xml='<protocols><pim><nonstop-routing/></pim></protocols>')
        if len(c) > 0:
            config_cmds.append('deactivate protocols pim nonstop-routing')
            # set a flag so we konw to turn it back on at the end
            self.pim_nonstop = True
        
        # Make configuration changes
        if config_cmds:
            logging.warn('Entering Configuration Mode...')
            logging.warn('-' * 24)

            try:
                with Config(self.dev, mode='exclusive') as cu:
                    for cmd in config_cmds:
                        cu.load(cmd, merge=True, ignore_warning=True)
                    logging.warn("Configuration Changes:")
                    logging.warn('-' * 24)
                    cu.pdiff()
                    if cu.diff():
                        if not self.yes_all:
                            cont = input('Commit Changes? (y/n): ')
                            if cont.lower() != 'y':
                                logging.warn('Rolling back changes...')
                                cu.rollback(rb_id=0)
                                exit()
                            else:
                                cu.commit()
                        else:
                            logging.warn('Committing changes...')
                            cu.commit()
                    else:
                        if not self.yes_all:
                            cont = input('No changes found to commit.  Continue upgrading router? (y/n): ')
                            if cont.lower() != 'y':
                                exit()
                        else:
                            logging.warn('No changes found to commit...')

            except RuntimeError as e:
                if "Ex: format='set'" in str(e):
                    logging.warn('ERROR: Unable to parse the PRE_UPGRADE_CMDS')
                    logging.warn('       Make sure they are formatted correctly.')
                else:
                    logging.warn('ERROR: {0}'.format(e))
                self.dev.close()
                exit()
        else:
            logging.warn("No pre-upgrade commands in CONFIG file")


    def upgrade_backup_re(self):
        """ Cycle through installing packcages for Dual RE systems """
        if not self.yes_all:
            cont = input("Continue with software add / reboot on backup RE? (y/n): ")
            if cont.lower() != 'y':
                res = input('Restore config changes before exiting? (y/n): ')
                if res.lower() == 'y':
                    self.restore_traffic()
                self.dev.close()
                exit()
        # First Stage Upgrade
        if self.two_stage:
            self.backup_re_pkg_add(CONFIG.CODE_2STAGE32, CONFIG.CODE_2STAGE64, CONFIG.CODE_PRESERVE)
        # Second Stage Upgrade
        self.backup_re_pkg_add(CONFIG.CODE_IMAGE32, CONFIG.CODE_IMAGE64, CONFIG.CODE_DEST)
        # JSU Upgrade
        if CONFIG.CODE_JSU32 or CONFIG.CODE_JSU64:
            if self.two_stage:
                self.backup_re_pkg_add(CONFIG.CODE_JSU32, CONFIG.CODE_JSU64, CONFIG.CODE_PRESERVE)
            else:
                self.backup_re_pkg_add(CONFIG.CODE_JSU32, CONFIG.CODE_JSU64, CONFIG.CODE_DEST)

   
    def backup_re_pkg_add(self, PKG32, PKG64, R_PATH):
        """ Perform software add and reboot the back RE """
        self.dev.timeout = 3600
        # Figure which RE is the current backup
        RE0, RE1 = False, False
        if self.dev.facts['master'] == 'RE0' and \
                    'backup' in self.dev.facts['RE1'].values():
            backup_RE = 'RE1'
            RE1 = True
        elif self.dev.facts['master'] == 'RE1' and \
                    'backup' in self.dev.facts['RE0'].values():
            backup_RE = 'RE0'
            RE0 = True
        else:
            logging.warn("Trouble finding the backup RE...")
            self.dev.close()
            exit()

        # Assign package path and name
        if self.arch == '32-bit':
            PACKAGE = CONFIG.CODE_DEST + PKG32
        else:
            PACKAGE = CONFIG.CODE_DEST + PKG64

        # Change flags for JSU vs JINSTALL Package:
        if 'jselective' in PACKAGE:
            NO_VALIDATE, REBOOT = False, False
        else:
            NO_VALIDATE, REBOOT = True, True

        # Add package and reboot the backup RE
        # Had issues w/utils.sw install, so im using the rpc call
        logging.warn('Installing ' + PACKAGE + ' on ' + backup_RE + '...')
        rsp = self.dev.rpc.request_package_add(reboot=REBOOT,
                                               no_validate=NO_VALIDATE,
                                               package_name=PACKAGE,
                                               re0=RE0, re1=RE1,
                                               force=self.force)

        # Check to see if the package add succeeded:
        ok = True
        got = rsp.getparent()
        for o in got.findall('output'):
            logging.warn(o.text)
        package_result = got.findall('package-result')
        for result in package_result:
            if result.text != '0':
                logging.warn('Pkgadd result ' + result.text)
                ok = False
        self.dev.timeout = 30
        if not ok:
            logging.warn('Encountered issues with software add...  Exiting')
            if not self.yes_all:
                cont = input('Rollback configuration changes? (y/n): ')
                if cont.lower() == 'y':
                    self.restore_traffic()
            else:
                self.restore_traffic()
            self.dev.close()
            exit()

        # Wait 2 minutes for package to install / reboot, then start checking every 30s
        time.sleep(120)
        re_state = 'Present'
        while re_state == 'Present':
            time.sleep(30)
            re_state = xmltodict.parse(etree.tostring(
                    self.dev.rpc.get_route_engine_information()))['route-engine-information']\
                    ['route-engine'][int(backup_RE[-1])]['mastership-state']

        # Give it 20 seconds, then check status
        time.sleep(20)
        re_status = xmltodict.parse(etree.tostring(
                self.dev.rpc.get_route_engine_information()))['route-engine-information']\
                ['route-engine'][int(backup_RE[-1])]['status']
        if re_status != 'OK':
            logging.warn('Backup RE state  = ' + re_state)
            logging.warn('Backup RE status = ' + re_status)

        # Grab core dump and SW version info
        self.dev.facts_refresh()
        if backup_RE == 'RE0':
            core_dump =  xmltodict.parse(etree.tostring(self.dev.rpc.get_system_core_dumps(re0=True)))
            sw_version = xmltodict.parse(etree.tostring(self.dev.rpc.get_software_information(re0=True)))
        elif backup_RE == 'RE1':
            core_dump =  xmltodict.parse(etree.tostring(self.dev.rpc.get_system_core_dumps(re1=True)))
            sw_version = xmltodict.parse(etree.tostring(self.dev.rpc.get_software_information(re1=True)))

        # Check for core dumps:
        logging.warn("Checking for core dumps...")
        for item in core_dump['multi-routing-engine-results']['multi-routing-engine-item']['directory-list']['output']:
            if 'No such file' not in item:
                logging.warn('Found Core Dumps!  Please investigate.')
                logging.warn(item)
                if not self.yes_all:
                    cont = input("Continue with upgrade? (y/n): ")
                    if cont.lower() != 'y':
                        self.dev.close()
                        exit()
        # Check SW Version:
        logging.warn(backup_RE + ' software version = ' + \
            sw_version['multi-routing-engine-results']['multi-routing-engine-item']['software-information']['junos-version'])


    def upgrade_single_re(self):
        """ Cycle through installing packcages for single RE systems """
        logging.warn("-----------------------------------------------------------")
        logging.warn("|  Ready to upgrade, THIS WILL BE SERVICE IMPACTING!!!    |")
        logging.warn("-----------------------------------------------------------")
        if not self.yes_all:
            cont = input("Continue with software add / reboot? (y/n): ")
            if cont.lower() != 'y':
                res = input('Restore config changes before exiting? (y/n): ')
                if res.lower() == 'y':
                    self.restore_traffic()
                self.dev.close()
                exit()

        # First Stage Upgrade
        if self.two_stage:
            self.single_re_pkg_add(CONFIG.CODE_2STAGE32, CONFIG.CODE_2STAGE64, CONFIG.CODE_PRESERVE)
        # Second Stage Upgrade
        self.single_re_pkg_add(CONFIG.CODE_IMAGE32, CONFIG.CODE_IMAGE64, CONFIG.CODE_DEST)
        # JSU Upgrade
        if CONFIG.CODE_JSU32 or CONFIG.CODE_JSU64:
            if self.two_stage:
                self.single_re_pkg_add(CONFIG.CODE_JSU32, CONFIG.CODE_JSU64, CONFIG.CODE_PRESERVE)
            else:
                self.single_re_pkg_add(CONFIG.CODE_JSU32, CONFIG.CODE_JSU64, CONFIG.CODE_DEST)


    def single_re_pkg_add(self, PKG32, PKG64, R_PATH):
        """ Perform software add and reboot the RE / Device """
        self.dev.timeout = 3600
        if self.arch == '32-bit':
            PACKAGE = CONFIG.CODE_DEST + PKG32
        else:
            PACKAGE = CONFIG.CODE_DEST + PKG64

        # Change flags for JSU vs JINSTALL Package:
        if 'jselective' in PACKAGE:
            NO_VALIDATE, REBOOT = False, False
        else:
            NO_VALIDATE, REBOOT = True, True

        # Request package add
        # Had issues w/utils.sw install, so im using the rpc call instead
        logging.warn('Upgrading device... Please Wait...')
        rsp = self.dev.rpc.request_package_add(reboot=REBOOT,
                                               no_validate=NO_VALIDATE,
                                               package_name=PACKAGE,
                                               force=self.force)
        
        # Check to see if the package add succeeded:
        ok = True
        got = rsp.getparent()
        for o in got.findall('output'):
            logging.warn(o.text)
        package_result = got.findall('package-result')
        for result in package_result:
            if result.text != '0':
                logging.warn('Pkgadd result ' + result.text)
                ok = False
        self.dev.timeout = 30
        if not ok:
            logging.warn('Encountered issues with software add...  Exiting')
            if not self.yes_all:
                cont = input("Restore configuration before exiting? (y/n): ")
                if cont.lower() == 'y':
                    self.restore_traffic()
                self.dev.close()
                exit()
            else:
                logging.warn('Restoring configuration before exiting...')
                self.restore_traffic()
                self.dev.close()
                exit()

        logging.warn("Rebooting Device, this may take a while...")
        # Wait 2 minutes for package to install and reboot, then start checking every 30s
        time.sleep(120)
        while self.dev.probe() == False:
            time.sleep(30)

        # Once dev is reachable, re-open connection (refresh facts first to kill conn)
        self.dev.facts_refresh()
        self.dev.open()
        self.dev.facts_refresh()

        # Check for core dumps:
        logging.warn("Checking for core dumps...")
        core_dump =  xmltodict.parse(etree.tostring(self.dev.rpc.get_system_core_dumps()))    
        for item in core_dump['multi-routing-engine-results']['multi-routing-engine-item']['directory-list']['output']:
            if 'No such file' not in item:
                logging.warn('Found Core Dumps!  Please investigate.')
                logging.warn(item)
                if not self.yes_all:
                    cont = input("Continue with upgrade? (y/n): ")
                    if cont.lower() != 'y':
                        self.dev.close()
                        exit()
        # Check SW Version:
        logging.warn('SW Version: ' + self.dev.facts['version'] + '')


    def switchover_RE(self):
        """ Issue RE switchover """
        if self.dev.facts['2RE']:
            logging.warn("-----------------------------------------------------------")
            logging.warn("|  Switch to backup RE, THIS WILL BE SERVICE IMPACTING!!! |")
            logging.warn("-----------------------------------------------------------")
            if not self.yes_all:
                cont = input('Continue with switchover? (y/n): ')
                if cont.lower() != 'y':
                    logging.warn("Exiting...")
                    self.dev.close()
                    exit()
            
            # Using dev.cli because I couldn't find an RPC call for switchover
            self.dev.timeout = 20
            logging.warn("Performing switchover to backup RE...")
            self.dev.cli('request chassis routing-engine master switch no-confirm')
            time.sleep(15)
            while self.dev.probe() == False:
                time.sleep(10)

            # Once dev is reachable, re-open connection (refresh facts first to kill conn)
            self.dev.facts_refresh()
            self.dev.open()
            self.dev.facts_refresh()

            # Add a check for task replication
            logging.warn('Checking task replication...')
            rep = xmltodict.parse(etree.tostring(
                    self.dev.rpc.get_routing_task_replication_state()))
            for k, v in rep['task-replication-state'].items():
                if v != 'Complete':
                    logging.warn('Protocol ' + k + ' is ' + v + '')


    def mx_network_services(self):
        """ Check if network-services mode enhanced-ip was requested, and set, reboot if not
            The reboot of both RE's was deemed nessicary by several issues where RE's were
            rebooted one at a time and did not sync network-services mode properly        """
        if self.dev.facts['model'][:2] == 'MX':
            if self.set_enhanced_ip:
                logging.warn("Setting chassis network-servies enhanced-ip...")
                try:
                    with Config(self.dev, mode='exclusive') as cu:
                        cu.load('set chassis network-services enhanced-ip',
                                 merge=True, ignore_warning=True)
                        cu.commit()
                except:
                    logging.warn('Error commtitting "set chassis network-services enhanced-ip"')
                    logging.warn('Device will not be rebooted, please check error configuring enhanced-ip')
                
                logging.warn("-----------------------------------------------------------")
                logging.warn("| SERVICE IMPACTING REBOOT WARNING                        |")
                logging.warn("-----------------------------------------------------------")

                cont = 'n'
                if not self.yes_all:
                    cont = input('Reboot both REs now to set network-services mode enhanced-ip? (y/n): ')
                else:
                    cont = 'y'
                if cont.lower() != 'y':
                    logging.warn("Skipping reboot of both RE's for network-services mode...")
                else:
                    logging.warn('Rebooting ' + self.host + '... Please wait...')
                    self.dev.timeout = 3600
                    self.dev.rpc.request_reboot(routing_engine='both-routing-engines')
                    # Wait 2 minutes for reboot, then start checking every 30s
                    time.sleep(120)
                    while self.dev.probe() == False:
                        time.sleep(30)
                    self.dev.facts_refresh()
                    self.dev.open()
                    self.dev.facts_refresh()


    def restore_traffic(self):
        """ Verify version, restore config, and wait for replication on dualRE """
        # Check SW Version:
        self.dev.facts_refresh()
        if self.dev.facts['2RE']:
            if self.dev.facts['version_RE0'] == self.dev.facts['version_RE1']:
                logging.warn('Version matches on both routing engines.')
            else:
                logging.warn('ERROR: Versions do not match on both routing engines')
                logging.warn('Exiting script, please check device status manually.')
                self.dev.close()
                exit()

        logging.warn('Restoring configruation...')
        config_cmds = CONFIG.POST_UPGRADE_CMDS

        # If pim nonstop-routing was deactivated, re-activate it
        if self.pim_nonstop:
            config_cmds.append('activate protocols pim nonstop-routing')

        if config_cmds:
            with Config(self.dev, mode='exclusive') as cu:
                for cmd in config_cmds:
                    cu.load(cmd, merge=True, ignore_warning=True)
                logging.warn("Configuration Changes:")
                logging.warn('-' * 24)
                cu.pdiff()
                if cu.diff():
                    if not self.yes_all:
                        cont = input('Commit Changes? (y/n): ')
                        if cont.lower() != 'y':
                            logging.warn('Rolling back changes...')
                            cu.rollback(rb_id=0)
                            exit()
                        else:
                            cu.commit()
                    else:
                        logging.warn('Committing Changes...')
                        cu.commit()
                else:
                    logging.warn('No changes found to commit...')
        else:
            logging.warn("No post-upgrade commands in CONFIG file")



    def switch_to_master(self):
        """ Switch back to the default master - RE0 """
        # Add a check for task replication
        if self.dev.facts['2RE']:
            logging.warn('Checking task replication...')
            task_sync = False
            while task_sync == False:
                rep = xmltodict.parse(etree.tostring(
                        self.dev.rpc.get_routing_task_replication_state()))
                task_sync = True
                for k, v in rep['task-replication-state'].items():
                    if v == 'InProgress':
                        task_sync = False
                        logging.warn('Protocol ' + k + ' is ' + v + '...  Waiting 2 minutes...')
                if task_sync == False:
                    time.sleep(120)

            # Check which RE is active and switchover if needed
            if self.dev.facts['re_master']['default'] == '1':
                if not self.yes_all:
                    cont = input('Task replication complete, switchover to RE0? (y/n): ')
                    if cont.lower() == 'y':
                        self.dev.timeout = 20
                        logging.warn("Performing final switchover to RE0...")
                        self.dev.cli('request chassis routing-engine master switch no-confirm')
                        time.sleep(15)
                        while self.dev.probe() == False:
                            time.sleep(10)
                        self.dev.facts_refresh()
                        self.dev.open()
                        self.dev.facts_refresh()
                else:
                    self.dev.timeout = 20
                    logging.warn("Performing final switchover to RE0...")
                    self.dev.cli('request chassis routing-engine master switch no-confirm')
                    time.sleep(15)
                    while self.dev.probe() == False:
                        time.sleep(10)
                    self.dev.facts_refresh()
                    self.dev.open()
                    self.dev.facts_refresh()


execute = RunUpgrade()

# 1. Get CLI Input / Print Usage Info
execute.get_arguments()
# 2. Setup Logging / Ensure Image is on local server
execute.initial_setup()
# 3. Open NETCONF Connection To Device
execute.open_connection()
# 4. Grab info on RE's
execute.collect_re_info()
# 5. Check For SW Image(s) on Device - Copy if needed
execute.image_check()
# 6. Request system snapshot
execute.system_snapshot()
# 7. Remove Redundancy / NSR, Overload ISIS, and check for Enhanced-IP
execute.remove_traffic()

# IF DEVICE IS SINGLE RE
if not execute.dev.facts['2RE']:
    # 8. Upgrade only RE
    execute.upgrade_single_re()
# IF DEVICE IS DUAL RE
else:
    # 8. Start upgrade on backup RE
    execute.upgrade_backup_re()
    # 9. Perform an RE Switchover
    execute.switchover_RE()
    # 10. Perform upgrade on the other RE
    execute.upgrade_backup_re()

# 11. Re-check network services mode on MX and reboot if needed
execute.mx_network_services()
# 12. Restore Routing-Engine redundancy
execute.restore_traffic()
#13. Switch back to RE0
execute.switch_to_master()

execute.dev.close()
logging.warn("Upgrade script complete, have a nice day!")
