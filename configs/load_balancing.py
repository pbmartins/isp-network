"""
Datacenter dynamic load balancing script

requeriments:
    pysnmp
    pysnmp-mibs
    statistics

Diogo Ferreira 76425
Pedro Martins  76551
"""

import os
import socket
import sys
import statistics
import time
from pysnmp.hlapi import *

# link infos
links = {
        '10.2.0.1': {
                'zone': 'aveiro',
                'changes': False,
                'usage_percentage': [],
                'link_up': True
            },
        '10.2.64.1': {
                'zone': 'oeiras',
                'changes': False,
                'usage_percentage': [],
                'link_up': True
            },
        # lisbon
        '10.2.128.1': {
                'zone': 'other',
                'changes': False,
                'usage_percentage': [],
                'link_up': True
        }
    }

# maximum usage percentage
maximum_percentage = 80

# maximum iterations with load greater than maximum percentage
maximum_overloaded_iterations = 5

def query_interfaces():        
    global links
    
    tmp_load = {}
    
    # query ten times, for delta calculations
    for i in range(10):
        # query all ips
        for ip in links:
            for (errorIndication,
                 errorStatus,
                 errorIndex,
                 varBinds) in nextCmd(SnmpEngine(),
                                    CommunityData('public'),
                                    UdpTransportTarget((ip, 161)),
                                    ContextData(),
                                    # get interface name
                                    ObjectType(ObjectIdentity('IF-MIB', 'ifDescr')),
                                    # get interface ip
                                    ObjectType(ObjectIdentity('1.3.6.1.2.1.4.20.1.2')),
                                    # get interface input load (bytes p/sec) 
                                    ObjectType(ObjectIdentity('IF-MIB', 'ifInOctets')),
                                    # get interface output load (bytes p/sec) 
                                    ObjectType(ObjectIdentity('IF-MIB', 'ifOutOctets')),
                                    # get interface speed (bits p/sec)
                                    ObjectType(ObjectIdentity('IF-MIB', 'ifSpeed')),
                                    lexicographicMode=False):

                if errorIndication:
                    # link is down
                    links[ip]['link_up'] = False
                    break
                elif errorStatus:
                    print('%s at %s' % (errorStatus.prettyPrint(), errorIndex
                            and varBinds[int(errorIndex)-1][0] or '?'))
                    break
                else:
                    # find interface
                    interface_ip_addr = varBinds[1][0].prettyPrint().split('20.1.2.')
                    if(len(interface_ip_addr) == 2 and interface_ip_addr[1] == ip):
                        # get interface intput and output load
                        in_load = int(varBinds[2][1].prettyPrint()) * 8
                        out_load = int(varBinds[3][1].prettyPrint()) * 8
                        # get interface speed
                        speed = int(varBinds[4][1].prettyPrint())

                        # save percentages
                        if (i > 0):
                            # compute delta values
                            delta_in_load = (in_load - tmp_load[ip]['in'])
                            delta_out_load = (out_load - tmp_load[ip]['out'])
                            delta_time = (time.time() - tmp_load[ip]['time'])

                            # compute usage percentage
                            usage_percentage = ((delta_in_load + delta_out_load) /
                                    (delta_time * speed)) * 100
                            
                            # save load percentage and state
                            links[ip]['usage_percentage'].append(usage_percentage)

                            # save link state
                            links[interface_ip_addr[1]]['link_up'] = True

                        # save temporary values
                        tmp_load[ip] = {
                            'in': in_load,
                            'out': out_load,
                            'time': time.time(),
                            'percentage': []
                        }
    
    # check link loads
    check_loads()


def check_loads():
    global links

    # get link with minimum load
    min_load = min(statistics.median(value['usage_percentage']) 
            for ip, value in links.items() if value['link_up'] )
    min_load_link = [ip for ip, value in links.items() if value['link_up'] 
            and statistics.median(value['usage_percentage']) == min_load]
    
    # all links have the same load or are all down, so keep the configs as they are
    if (len(min_load_link) == 0 or len(min_load_link) == 3):
        return

    # get interface with lower load
    min_load_link = min_load_link[-1]

    changes = False
    for ip, infos in links.items():
        link_up = infos['link_up']
        overloaded_iterations = sum(load > maximum_percentage 
                for load in infos['usage_percentage'])
        if (not link_up or overloaded_iterations >= maximum_overloaded_iterations):
            # change dns configuration to point to link with least load
            change_config(links[ip]['zone'], links[min_load_link]['zone'])
            # signal change
            links[ip]['changes'] = changes = True
        elif (links[ip]['changes']):
            # replace original configuration
            change_config(links[ip]['zone'], links[ip]['zone'])
            # Reset changes
            links[ip]['changes'] = False
            changes = True

    # force bind9 service restart
    if (changes):
        os.system('sudo service bind9 restart')


def change_config(zone, new_zone):
    # create symlink to new filezone
    src_filename = '/etc/bind/' + new_zone + '-db'
    dst_filename = '/etc/bind/aracdn.pt-' + zone + '-db'

    os.remove(dst_filename)
    os.symlink(src_filename, dst_filename)
    
    # print info log
    print('>>> Zone ' + zone + ' updated - now beeing redirected to ' + new_zone)


if __name__ == "__main__":
   
    # script needs sudo to restart bind9
    if (os.getuid() != 0):
        print('This script needs super user privileges')
        sys.exit(0)

    # query interfaces at each 2 minutes
    while True:
        print('Checking interfaces load...')
        query_interfaces()
        time.sleep(120)
