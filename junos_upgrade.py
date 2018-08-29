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
from jnpr.junos.exception import ConnectError, CommitError
from netmiko import ConnectHandler
from datetime import datetime
from ltoken import ltoken
from lxml import etree
import xmltodict
import argparse
import json
import yaml


class RunUpgrade(object):
    def __init__(self):
        self.arch = ''
        self.host = ''
        self.auth = ltoken()
        self.config = {}
        self.configfile = '/opt/ipeng/scripts/jtishey/junos_upgrade/config.yml'
        self.force = False
        self.yes_all = False
        self.no_install = False
        self.set_enhanced_ip = False
        self.pim_nonstop = False
        self.two_stage = False


    def get_arguments(self):
        """ Handle input from CLI """
        p = argparse.ArgumentParser(
            description='Parse and compare before/after baseline files.',
            formatter_class=lambda prog: argparse.HelpFormatter(prog,max_help_position=32))
        p.add_argument('-d', '--device', help='Specify an IP or hostname to upgrade',
                        required=True, metavar='DEV')
        p.add_argument('-c', '--config', help='Specify an alternate config file', metavar='CFG')
        p.add_argument('-f', '--force', action='count', default=0, 
                        help='Use "force" option on all package adds (DANGER!)')
        p.add_argument('-n', '--noinstall', action='count', default=0,
                        help='Do a dry-run, check for files and copying them only')
        p.add_argument('-y', '--yes_all', action='count', default=0,
                        help='Answer "y" to all questions during the upgrade (DANGER!)')
        args = vars(p.parse_args())
        self.host = args['device']
        if args['config']:
            self.config = args['config']
        if args['force']:
            self.force - True
        if args['noinstall']:
            self.no_install = True
        if args['yes_all']:
            self.yes_all = True


    def initial_setup(self):
        """ Setup logging and check for the image on the server """
        logfile = self.host + '_upgrade.log'
        logging.basicConfig(filename=logfile, level=logging.WARN,
                            format='%(asctime)s:%(name)s: %(message)s')
        logging.getLogger().name = self.host
        logging.getLogger().addHandler(logging.StreamHandler())
        logging.warn('Information logged in {0}'.format(logfile))

        """ Open the self.config['yml file and load code versions and options """
        try:
            with open(self.configfile) as f:
                self.config = yaml.load(f)
        except:
            logging.warn("ERROR: Issues opening config file {0}".format(self.configfile))
            exit(1)

        # verify package exists on local server
        if not (os.path.isfile(self.config['CODE_FOLDER'] + self.config['CODE_IMAGE64'])):
            msg = 'Software package does not exist: {0}. '.format(
                                self.config['CODE_FOLDER'] + self.config['CODE_IMAGE64'])
            logging.error(msg)
            self.end_script()


    def open_connection(self):
        """ Open a NETCONF connection to the device """
        if self.no_install:
            logging.warn('Running with no_install option - copy files only...')
        try:
            logging.warn('Connecting to ' + self.host + '...')
            self.dev = Device(host=self.host,
                              user=self.auth['username'],
                              password=self.auth['password'],
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
                logging.warn('            RE0   \t RE1')
                logging.warn('Mastership: {0} \t {1}'.format(
                                                self.dev.facts['RE0']['mastership_state'],
                                                self.dev.facts['RE1']['mastership_state']))
                logging.warn('Status:     {0} \t\t {1}'.format(
                                                self.dev.facts['RE0']['status'],
                                                self.dev.facts['RE1']['status']))
                logging.warn('Model:      {0} \t {1}'.format(
                                                self.dev.facts['RE0']['model'],
                                                self.dev.facts['RE1']['model']))
                logging.warn('Version:    {0} \t {1}'.format(
                                                self.dev.facts['version_RE0'],
                                                self.dev.facts['version_RE1']))
            else:
                logging.warn('              RE0  ')
                logging.warn('Mastership: {0}'.format(self.dev.facts['RE0']['mastership_state'] + ''))
                logging.warn('Status:     {0}'.format(self.dev.facts['RE0']['status'] + ''))
                logging.warn('Model:      {0}'.format(self.dev.facts['RE0']['model'] + ''))
                logging.warn('Version:    {0}'.format(self.dev.facts['version'] + ''))
            logging.warn("")
    
            # Check for redundant REs
            logging.warn('Checking for redundant routing-engines...')
            if not self.dev.facts['2RE']:
                if not self.yes_all:
                    re_stop = input("Redundant RE's not found, Continue? (y/n): ")
                    if re_stop.lower() != 'y':
                        self.end_script()
                else:
                    logging.warn("Redundant RE's not found...")

      
    def copy_image(self, source, dest):
        """ Copy files via SCP """
        logging.warn("Image not found on active RE, copying now...")
        try:
            with SCP(self.dev, progress=True) as scp:
                logging.warn("Copying image to " + dest + "...")
                scp.put(source, remote_path=dest)
        except Exception as e:
            logging.warn(str(e))
            self.end_script()


    def copy_to_other_re(self, source, dest):
        """
        Use netmiko to copy files from one RE to the other because PyEZ doesnt allow this
            :param source: source file, including re:/ prefix
            :param dest:  destination location, including re:/ prefix
        """
        logging.warn("Image not found on backup RE, copying now...")
        d = {'device_type': 'juniper',
             'ip': self.host,
             'username': self.auth['username'],
             'password': self.auth['password']}
        try:
            net_connect = ConnectHandler(**d)
            net_connect.send_command("file copy " + source + " " + dest)
            net_connect.disconnect()
        except:
            logging.warn("Error copying file to other RE, Please login and do this manually")
            logging.warn("CMD: file copy " + source + " " + dest)


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
                logging.warn("Using 64-bit Image...")
            else:
                self.arch = '32-bit'
                logging.warn("Using 32-bit Image...")

        # Are we doing a two-stage upgrade? (Reqd for >3 major version change)
        if self.config['CODE_2STAGE32'] or self.config['CODE_2STAGE64']:
            if self.dev.facts['version'][:2] == self.config['CODE_2STAGEFOR']:
                logging.warn('Two-Stage Upgrade will be performed...')
                self.two_stage = True
        
        # Define all the file names / paths
        if self.arch == '32-bit':
            source = self.config['CODE_FOLDER'] + self.config['CODE_IMAGE32']
            source_2stg = self.config['CODE_FOLDER'] + self.config['CODE_2STAGE32']
            source_jsu = self.config['CODE_FOLDER'] + self.config['CODE_JSU32']
            if self.two_stage:
                dest = self.config['CODE_PRESERVE'] + self.config['CODE_2STAGE32']
                dest_2stg = self.config['CODE_DEST'] + self.config['CODE_IMAGE32']
                dest_jsu = self.config['CODE_PRESERVE'] + self.config['CODE_JSU32']
            else:
                dest = self.config['CODE_DEST'] + self.config['CODE_IMAGE32']
                dest_jsu = self.config['CODE_DEST'] + self.config['CODE_JSU32']            
        elif self.arch == '64-bit':
            source = self.config['CODE_FOLDER'] + self.config['CODE_IMAGE64']
            source_2stg = self.config['CODE_FOLDER'] + self.config['CODE_2STAGE64']
            source_jsu = self.config['CODE_FOLDER'] + self.config['CODE_JSU64']
            if self.two_stage:
                dest = self.config['CODE_PRESERVE'] + self.config['CODE_2STAGE64']
                dest_2stg = self.config['CODE_DEST'] + self.config['CODE_IMAGE64']
                dest_jsu = self.config['CODE_PRESERVE'] + self.config['CODE_JSU64']
            else:
                dest = self.config['CODE_DEST'] + self.config['CODE_IMAGE64']
                dest_jsu = self.config['CODE_DEST'] + self.config['CODE_JSU64']     

        # Check for final software image on the device
        logging.warn('Checking for image on the active RE...')
        img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=dest)))
        img_output = json.dumps(img)
        if 'No such file' in img_output:
            self.copy_image(source, dest)

        # If dual RE - Check backup RE too
        if self.dev.facts['2RE']:
            if self.dev.facts['master'] == 'RE0':
                active_RE = 're0:'
                backup_RE = 're1:'
            else:
                active_RE = 're1:'
                backup_RE = 're0:'
            logging.warn('Checking for image on the backup RE...')
            img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=backup_RE + dest)))
            img_output = json.dumps(img)
            if 'No such file' in img_output:
                self.copy_to_other_re(active_RE + dest, backup_RE + dest)
                img = xmltodict.parse(etree.tostring(self.dev.rpc.file_list(path=backup_RE + dest)))
                img_output = json.dumps(img)
                if 'No such file' in img_output:
                    msg = 'file copy ' + dest + ' ' + backup_RE + dest
                    logging.warn('ERROR: Copy the image to the backup RE, then re-run script')
                    logging.warn('CMD  : ' + msg)
                    self.end_script()

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
                    self.copy_to_other_re(active_RE + dest_2stg, backup_RE + dest_2stg)
                    # Check again
                    img = xmltodict.parse(etree.tostring(
                            self.dev.rpc.file_list(path=backup_RE + dest_2stg)))
                    img_output = json.dumps(img)
                    if 'No such file' in img_output:
                        msg = 'file copy ' + active_RE + dest_2stg + ' ' + backup_RE + dest_2stg
                        logging.warn('ERROR: Copy the image to the backup RE, then re-run script')
                        logging.warn('CMD  : ' + msg)
                        self.end_script()
                    
        # Check if JSU Install is requested (present in self.config['py)
        if self.config['CODE_JSU32'] or self.config['CODE_JSU64']:
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
                    self.copy_to_other_re(active_RE + dest_jsu, backup_RE + dest_jsu)
                    img = xmltodict.parse(etree.tostring(
                            self.dev.rpc.file_list(path=backup_RE + dest_jsu)))
                    img_output = json.dumps(img)
                    if 'No such file' in img_output:
                        msg = 'file copy ' + active_RE + dest_jsu + ' ' + backup_RE + dest_jsu
                        logging.warn('ERROR: Copy the image to the backup RE, then re-run script')
                        logging.warn('CMD  : ' + msg)
                        self.end_script()


    def system_snapshot(self):
        """ Performs [request system snapshot] on the device """
        logging.warn('Requesting system snapshot on RE0...')
        self.dev.timeout = 240
        try:
            snap = xmltodict.parse(etree.tostring(self.dev.rpc.request_snapshot(re0=True)))
            if 'error' in json.dumps(snap):
                logging.warn("Error taking snapshot... Please check device logs")

            if self.dev.facts['2RE']:
                logging.warn('Requesting system snapshot on RE1...')
                snap = xmltodict.parse(etree.tostring(self.dev.rpc.request_snapshot(re1=True)))
                if 'error' in json.dumps(snap):
                    logging.warn("Error taking snapshot... Please check device logs")
        except Exception as e:
            logging.warn('ERROR: Problem with snapshots')
            logging.warn(str(e))


    def remove_traffic(self):
        """ Execute the PRE_UPGRADE_CMDS from the self.config['py file to remove traffic """
        config_cmds = self.config['PRE_UPGRADE_CMDS']
        
        # Network Service check on MX Platform
        if self.dev.facts['model'][:2] == 'MX':
            logging.warn("Checking for network-services enhanced-ip...")
            dpc_flag = False
            net_mode = xmltodict.parse(etree.tostring(
                        self.dev.rpc.network_services()))
            cur_mode = net_mode['network-services']['network-services-information']['name']
            if cur_mode != 'Enhanced-IP':
                # Check for DPCs
                logging.warn("Checking for any installed DPCs...")
                hw = xmltodict.parse(etree.tostring(
                        self.dev.rpc.get_chassis_inventory(models=True)))
                for item in hw['chassis-inventory']['chassis']['chassis-module']:
                    if item['description'][:3] == 'DPC':
                        dpc_flag = True
                        
                if dpc_flag:
                    logging.warn("Chassis has DPCs installed, skipping network-services change")
                else:
                    logging.warn('Network Services mode is ' + cur_mode + '')
                    if not self.yes_all:
                        cont = self.input_parse('Change Network Services Mode to Enhanced-IP? (y/n): ')
                        if cont == 'y':
                            # Set a flag to recheck at the end and reboot if needed:
                            self.set_enhanced_ip = True
                    else:
                        self.set_enhanced_ip = True
        
        # PIM nonstop-routing must be removed if it's there to deactivate GRES
        pim = self.dev.rpc.get_config(filter_xml='<protocols><pim><nonstop-routing/></pim></protocols>')
        if len(pim) > 0:
            config_cmds.append('deactivate protocols pim nonstop-routing')
            # set a flag so we konw to turn it back on at the end
            self.pim_nonstop = True
        
        # Make configuration changes
        if config_cmds:
            logging.warn('Entering Configuration Mode...')
            logging.warn('-' * 24)
            success = True
            try:
                with Config(self.dev, mode='exclusive') as cu:
                    for cmd in config_cmds:
                        cu.load(cmd, merge=True, ignore_warning=True)
                    logging.warn("Configuration Changes:")
                    logging.warn('-' * 24)
                    cu.pdiff()
                    if cu.diff():
                        if not self.yes_all:
                            cont = self.input_parse('Commit Changes? (y/n): ')
                            if cont =='y':
                                try:
                                    cu.commit()
                                except CommitError as e:
                                    logging.warn("Error committing changes")
                                    logging.warn(str(e))
                            else:
                                logging.warn('Rolling back changes...')
                                cu.rollback(rb_id=0)
                                success = False
                        else:
                            logging.warn('Committing changes...')
                            try:
                                cu.commit()
                            except CommitError as e:
                                logging.warn("Error committing changes")
                                logging.warn(str(e))
                    else:
                        logging.warn('No changes found to commit...')
            except RuntimeError as e:
                if "Ex: format='set'" in str(e):
                    logging.warn('ERROR: Unable to parse the PRE_UPGRADE_CMDS')
                    logging.warn('       Make sure they are formatted correctly.')
                else:
                    logging.warn('ERROR: {0}'.format(e))
                success = False
            if not success:
                self.end_script()
        else:
            logging.warn("No pre-upgrade commands in CONFIG file")


    def upgrade_backup_re(self):
        """ Cycle through installing packcages for Dual RE systems """
        # First Stage Upgrade
        if self.two_stage:
            self.backup_re_pkg_add(self.config['CODE_2STAGE32'], self.config['CODE_2STAGE64'], self.config['CODE_PRESERVE'])
        # Second Stage Upgrade
        self.backup_re_pkg_add(self.config['CODE_IMAGE32'], self.config['CODE_IMAGE64'], self.config['CODE_DEST'])
        # JSU Upgrade
        if self.config['CODE_JSU32'] or self.config['CODE_JSU64']:
            if self.two_stage:
                self.backup_re_pkg_add(self.config['CODE_JSU32'], self.config['CODE_JSU64'], self.config['CODE_PRESERVE'])
            else:
                self.backup_re_pkg_add(self.config['CODE_JSU32'], self.config['CODE_JSU64'], self.config['CODE_DEST'])

   
    def backup_re_pkg_add(self, PKG32, PKG64, R_PATH):
        """ Perform software add and reboot the back RE """
        self.dev.timeout = 3600
        # Figure which RE is the current backup
        RE0, RE1 = False, False
        if self.dev.facts['master'] == 'RE0' and \
                    'backup' in self.dev.facts['RE1'].values():
            active_RE = 'RE0'
            backup_RE = 'RE1'
            RE1 = True
        elif self.dev.facts['master'] == 'RE1' and \
                    'backup' in self.dev.facts['RE0'].values():
            active_RE = 'RE1'
            backup_RE = 'RE0'
            RE0 = True
        else:
            logging.warn("Trouble finding the backup RE...")
            self.end_script()

        # Assign package path and name
        if self.arch == '32-bit':
            PACKAGE = R_PATH + PKG32
        else:
            PACKAGE = R_PATH + PKG64

        # Add package and reboot the backup RE
        # Had issues w/utils.sw install, so im using the rpc call instead
        startTime = datetime.now()
        logging.warn('Installing ' + PACKAGE + ' on ' + backup_RE + '...')
        # Change flags for JSU vs JINSTALL Package:
        if 'jselective' in PACKAGE:
            # Not clear if it will barf on adding an "rex=False" for the JSU yet
            if RE0:
                rsp = self.dev.rpc.request_package_add(package_name=PACKAGE, re0=True)
            elif RE1:
                rsp = self.dev.rpc.request_package_add(package_name=PACKAGE, re1=True)
        else:
            rsp = self.dev.rpc.request_package_add(reboot=True, no_validate=True,
                                                   package_name=PACKAGE, re0=RE0, re1=RE1,
                                                   force=self.force)
        # Check to see if the package add succeeded:
        logging.warn('-----------------START PKG ADD OUTPUT-----------------')
        ok = True
        for o in rsp.getparent().findall('output'):
            logging.warn(o.text)
        for result in rsp.getparent().findall('package-result'):
            if result.text != '0':
                logging.warn('Pkgadd result ' + result.text)
                ok = False
        logging.warn('------------------END PKG ADD OUTPUT------------------')
        if not ok:
            self.dev.timeout = 60
            logging.warn('Encountered issues with software add...  Exiting')
            if not self.yes_all:
                cont = self.input_parse('Rollback configuration changes? (y/n): ')
                if cont == 'y':
                    self.restore_traffic()
            else:
                self.restore_traffic()
            logging.warn("Script complete, please check the package add errors manually")
            self.end_script()

        # Wait 2 minutes for package to install / reboot, then start checking every 30s
        time.sleep(120)
        re_state = 'Present'
        while re_state == 'Present':
            time.sleep(30)
            re_state = xmltodict.parse(etree.tostring(
                    self.dev.rpc.get_route_engine_information()))['route-engine-information']\
                    ['route-engine'][int(backup_RE[-1])]['mastership-state']

        # Give it 20 seconds, then check status again
        time.sleep(20)
        re_status = xmltodict.parse(etree.tostring(
                self.dev.rpc.get_route_engine_information()))['route-engine-information']\
                ['route-engine'][int(backup_RE[-1])]['status']
        if re_status != 'OK':
            logging.warn('Backup RE state  = ' + re_state)
            logging.warn('Backup RE status = ' + re_status)

        logging.warn("Package " + PACKAGE + " took {0}".format(
                        str(datetime.now() - startTime).split('.')[0]))

        # Grab core dump and SW version info
        self.dev.facts_refresh()
        core_dump =  xmltodict.parse(etree.tostring(self.dev.rpc.get_system_core_dumps(re0=RE0, re1=RE1)))
        sw_version = xmltodict.parse(etree.tostring(self.dev.rpc.get_software_information(re0=RE0, re1=RE1)))
        
        # Check for core dumps:
        logging.warn("Checking for core dumps...")
        if 'directory' in core_dump['multi-routing-engine-results']['multi-routing-engine-item']['directory-list'].keys():
            logging.warn('Found Core Dumps!  Please investigate.')
            cont = self.input_parse("Continue with upgrade? (y/n): ")
            if cont == 'n':
                cont = self.input_parse("Revert config changes? (y/n): ")
                if cont == 'y':
                    self.restore_traffic()
                self.end_script()
        # Check SW Version:
        logging.warn(backup_RE + ' software version = ' + \
            sw_version['multi-routing-engine-results']['multi-routing-engine-item']['software-information']['junos-version'])

        # Copy the final image back to the RE if needed after installing 
        if self.arch == '64-bit':
            final_image = self.config['CODE_DEST'] + self.config['CODE_IMAGE64']
        else:
            final_image = self.config['CODE_DEST'] + self.config['CODE_IMAGE32']
        
        img = xmltodict.parse(etree.tostring(
                self.dev.rpc.file_list(path=backup_RE.lower() + ':' + final_image)))
        img_output = json.dumps(img)
        if 'No such file' in img_output:
            self.copy_to_other_re(active_RE.lower() + ':' + final_image, backup_RE.lower() + ':' + final_image)
            img = xmltodict.parse(etree.tostring(
                    self.dev.rpc.file_list(path=backup_RE.lower() + ':' + final_image)))
            img_output = json.dumps(img)
            if 'No such file' in img_output:
                msg = 'file copy ' + active_RE.lower() + ':' + final_image + ' ' + backup_RE + ':' + final_image
                logging.warn('ERROR: Copy the image to the backup RE manually')
                logging.warn('CMD  : ' + msg)


    def upgrade_single_re(self):
        """ Cycle through installing packcages for single RE systems """
        logging.warn("------------------------WARNING-----------------------------")
        logging.warn("Ready to upgrade, THIS WILL BE SERVICE IMPACTING!!!        ")
        logging.warn("-----------------------------------------------------------")
        if not self.yes_all:
            cont = self.input_parse("Continue with software add / reboot? (y/n): ")
            if cont != 'y':
                self.restore_traffic()
                self.end_script()

        # First Stage Upgrade
        if self.two_stage:
            self.single_re_pkg_add(self.config['CODE_2STAGE32'], self.config['CODE_2STAGE64'], self.config['CODE_PRESERVE'])
        # Second Stage Upgrade
        self.single_re_pkg_add(self.config['CODE_IMAGE32'], self.config['CODE_IMAGE64'], self.config['CODE_DEST'])
        # JSU Upgrade
        if self.config['CODE_JSU32'] or self.config['CODE_JSU64']:
            if self.two_stage:
                self.single_re_pkg_add(self.config['CODE_JSU32'], self.config['CODE_JSU64'], self.config['CODE_PRESERVE'])
            else:
                self.single_re_pkg_add(self.config['CODE_JSU32'], self.config['CODE_JSU64'], self.config['CODE_DEST'])


    def single_re_pkg_add(self, PKG32, PKG64, R_PATH):
        """ Perform software add and reboot the RE / Device """
        self.dev.timeout = 3600
        if self.arch == '32-bit':
            PACKAGE = self.config['CODE_DEST'] + PKG32
        else:
            PACKAGE = self.config['CODE_DEST'] + PKG64
        # Had issues w/utils.sw install, so im using the rpc call instead
        startTime = datetime.now()
        logging.warn('Upgrading device... Please Wait...')
        # Change flags for JSU vs JINSTALL Package:
        if 'jselective' in PACKAGE:
            rsp = self.dev.rpc.request_package_add(package_name=PACKAGE)
        else:
            rsp = self.dev.rpc.request_package_add(reboot=True,
                                               no_validate=True,
                                               package_name=PACKAGE,
                                               force=self.force)
        
        # Check to see if the package add succeeded:
        logging.warn('-----------------START PKG ADD OUTPUT-----------------')
        ok = True
        got = rsp.getparent()
        for o in got.findall('output'):
            logging.warn(o.text)
        package_result = got.findall('package-result')
        for result in package_result:
            if result.text != '0':
                logging.warn('Pkgadd result ' + result.text)
                ok = False
        self.dev.timeout = 120
        logging.warn('------------------END PKG ADD OUTPUT------------------')
        if not ok:
            logging.warn('Encountered issues with software add...  Exiting')
            if not self.yes_all:
                cont = self.input_parse("Restore configuration before exiting? (y/n): ")
                if cont == 'y':
                    self.restore_traffic()
                self.end_script()
            else:
                logging.warn('Restoring configuration before exiting...')
                self.restore_traffic()
                self.end_script()

        logging.warn("Rebooting Device, this may take a while...")
        # Wait 2 minutes for package to install and reboot, then start checking every 30s
        time.sleep(120)
        while self.dev.probe() == False:
            time.sleep(30)
        
        logging.warn("Package " + PACKAGE + " took {0}".format(
                        str(datetime.now() - startTime).split('.')[0]))
        
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
                    cont = self.input_parse("Continue with upgrade? (y/n): ")
                    if cont.lower() != 'y':
                        self.end_script()
        # Check SW Version:
        logging.warn('SW Version: ' + self.dev.facts['version'] + '')


    def switchover_RE(self):
        """ Issue RE switchover """
        if self.dev.facts['2RE']:
            # Add a check for GRES / NSR
            x = self.dev.rpc.get_nonstop_routing_information()
            for item in x.getparent().iter():
                if item.findtext('nonstop-routing-enabled'):
                    nsr = item.findtext('nonstop-routing-enabled')
            if nsr != 'Enabled':
                logging.warn("----------------------WARNING----------------------------")
                logging.warn('Nonstop-Routing is {0}, switchover will be impacting!'.format(nsr))
                logging.warn("---------------------------------------------------------")
            if not self.yes_all:
                cont = self.input_parse('Continue with switchover? (y/n): ')
                if cont != 'y':
                    self.end_script()
            # Using dev.cli because I couldn't find an RPC call for switchover
            self.dev.timeout = 20
            logging.warn("Performing routing-engine switchover...")
            try:
                self.dev.cli('request chassis routing-engine master switch no-confirm')
            except:
                self.dev.close()
            time.sleep(15)
            while self.dev.probe() == False:
                time.sleep(10)
            # Once dev is reachable, re-open connection (refresh facts first to kill conn)
            self.dev.open()


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
                        cu.commit(sync=True, full=True)
                except:
                    logging.warn('Error commtitting "set chassis network-services enhanced-ip"')
                    logging.warn('Device will not be rebooted, please check error configuring enhanced-ip')
                
                logging.warn("-----------------------WARNING------------------------------")
                logging.warn("SERVICE IMPACTING REBOOT WARNING")
                logging.warn("-----------------------------------------------------------")

                if not self.yes_all:
                    cont = self.input_parse('Reboot both REs now to set network-services mode enhanced-ip? (y/n): ')
                else:
                    cont = 'y'
                if cont != 'y':
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


    def input_parse(self, msg):
        """ Prompt for input """
        q = ''
        while q.lower() != 'y' and q.lower() != 'n':
            q = input(msg)
        return q.lower()


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
                self.end_script()

        logging.warn('Restoring configruation...')
        config_cmds = self.config['POST_UPGRADE_CMDS']

        # If pim nonstop-routing was deactivated, re-activate it
        if self.pim_nonstop:
            config_cmds.append('activate protocols pim nonstop-routing')

        if config_cmds:
            success = True
            with Config(self.dev, mode='exclusive') as cu:
                for cmd in config_cmds:
                    cu.load(cmd, merge=True, ignore_warning=True)
                logging.warn("Configuration Changes:")
                logging.warn('-' * 24)
                cu.pdiff()
                if cu.diff():
                    if not self.yes_all:
                        cont = self.input_parse('Commit Changes? (y/n): ')
                        if cont != 'y':
                            logging.warn('Rolling back changes...')
                            cu.rollback(rb_id=0)
                            success = False
                        else:
                            try:
                                if self.dev.facts['2RE']:
                                    cu.commit(sync=True, full=True)
                                else:
                                    cu.commit(full=True)
                            except CommitError as e:
                                logging.warn("Error committing changes")
                                logging.warn(str(e))
                    else:
                        logging.warn('Committing Changes...')
                        try:
                            if self.dev.facts['2RE']:
                                cu.commit(sync=True, full=True)
                            else:
                                cu.commit(full=True)
                        except CommitError as e:
                            logging.warn("Error committing changes")
                            logging.warn(str(e))
            if not success:
                self.end_script()
        else:
            logging.warn("No post-upgrade commands in CONFIG file")


    def switch_to_master(self):
        """ Switch back to the default master - RE0 """
        if self.dev.facts['2RE']:
            # Add a check for task replication
            logging.warn('Checking task replication...')
            task_sync = False
            waiting_on = ''
            while task_sync == False:
                rep = xmltodict.parse(etree.tostring(
                        self.dev.rpc.get_routing_task_replication_state()))
                task_sync = True
                for i, item in enumerate(rep['task-replication-state']['task-protocol-replication-state']):
                    if item != 'Complete':
                        task_sync = False
                        proto = rep['task-replication-state']['task-protocol-replication-name'][i]
                        if waiting_on != proto:
                            waiting_on = proto
                            logging.warn(proto + ': ' + item + '...')
                if task_sync == False:
                    time.sleep(60)
            # Check which RE is active and switchover if needed
            if self.dev.facts['RE0']['mastership_state'] != 'master':
                self.switchover_RE()


    def end_script(self):
        """ Close the connection to the device and exit the script """
        try:
            logging.warn("Disconnecting from {0}...".format(self.host))
            self.dev.close()
        except:
            logging.warn("Did not disconnect cleanly.")
        exit()


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

# Quit here if the --noinstall option is present
if execute.no_install:
    logging.warn("Run without the -n / --noupgrade option to install")
    execute.end_script()

# 6. Request system snapshot
execute.system_snapshot()
# 7. Remove Redundancy / NSR, Pre-Upgrade config changes
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
# 13. Switch back to RE0
execute.switch_to_master()
# 14. Request system snapshot
execute.system_snapshot()
# 15. Display results
logging.warn("------------------------")
logging.warn("|       RESULTS        |")
logging.warn("------------------------")
execute.collect_re_info()

execute.end_script()
