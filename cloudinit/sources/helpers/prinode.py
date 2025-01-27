# Author: Emil Jönsson <emil@prinode.com>
# Partially based on DataSourceVultr
#
# This file is part of cloud-init. See LICENSE file for license information.

import json

from cloudinit import log as log
from cloudinit import url_helper
from cloudinit import dmi
from cloudinit import util
from cloudinit import net
from cloudinit.net.dhcp import EphemeralDHCPv4, NoDHCPLeaseError
from functools import lru_cache

# Get LOG
LOG = log.getLogger(__name__)

@lru_cache()
def get_metadata(url, timeout, retries, sec_between, agent):
    # Bring up interface
    try:
        with EphemeralDHCPv4(connectivity_url=url):
            # Fetch the metadata
            v1 = read_metadata(url, timeout, retries, sec_between, agent)
    except (NoDHCPLeaseError) as exc:
        LOG.error("Bailing, DHCP Exception: %s", exc)
        raise

    return json.loads(v1)


# Read the system information from SMBIOS
def get_sysinfo():
    return {
        'manufacturer': dmi.read_dmi_data("system-manufacturer"),
        'subid': dmi.read_dmi_data("system-serial-number")
    }

# Look for 'Prinode' in smbios
# XML: <sysinfo type='smbios'><system><entry name='manufacturer'>Prinode</entry>
# Assumes is Prinode is already checked
# def is_baremetal():
#     if get_sysinfo()['manufacturer'] != "Prinode":
#         return True
#     return False


# Confirm is Prinode
def is_prinode():
    # VC2, VDC, and HFC use DMI
    sysinfo = get_sysinfo()

    if sysinfo['manufacturer'] == "Prinode":
        return True
    else:
        return False

    # Baremetal requires a kernel parameter
    # if "prinode" in util.get_cmdline().split():
    #    return True

    # return False


# Read Metadata endpoint
def read_metadata(url, timeout, retries, sec_between, agent):
    url = "%s/v1.json" % url

    # Announce os details so we can handle non Prinode origin
    # images and provide correct vendordata generation.
    headers = {
        'Metadata-Token': 'cloudinit',
        'User-Agent': agent
    }

    response = url_helper.readurl(url,
                                  timeout=timeout,
                                  retries=retries,
                                  headers=headers,
                                  sec_between=sec_between)

    if not response.ok():
        raise RuntimeError("Failed to connect to %s: Code: %s" %
                           url, response.code)

    return response.contents.decode()


# Wrapped for caching
@lru_cache()
def get_interface_map():
    return net.get_interfaces_by_mac()


# Convert macs to nics
def get_interface_name(mac):
    macs_to_nic = get_interface_map()

    if mac not in macs_to_nic:
        return None

    return macs_to_nic.get(mac)


# Generate network configs
def generate_network_config(interfaces):
    network = {
        "version": 1,
        "config": [
            {
                "type": "nameserver",
                "address": [
                    "1.1.1.1"
                ]
            }
        ]
    }

    # Prepare interface 0, public
    if len(interfaces) > 0:
        public = generate_public_network_interface(interfaces[0])
        network['config'].append(public)

    # Prepare additional interfaces, private
    for i in range(1, len(interfaces)):
        private = generate_private_network_interface(interfaces[i])
        network['config'].append(private)

    return network


# Input Metadata and generate public network config part
def generate_public_network_interface(interface):
    interface_name = get_interface_name(interface['mac'])
    if not interface_name:
        raise RuntimeError(
            "Interface: %s could not be found on the system" %
            interface['mac'])

    netcfg = {
        "name": interface_name,
        "type": "physical",
        "mac_address": interface['mac'],
        "accept-ra": 1,
        "subnets": [
            {
                "type": "dhcp",
                "control": "auto"
            },
        ]
    }

    # Check for additional IP's
    additional_count = len(interface['ipv4']['additional'])
    if "ipv4" in interface and additional_count > 0:
        for additional in interface['ipv4']['additional']:
            add = {
                "type": "static",
                "control": "auto",
                "address": additional['address'],
                "netmask": additional['netmask']
            }
            netcfg['subnets'].append(add)

    # Check for additional IPv6's
    # additional_count = len(interface['ipv6']['additional'])
    # if "ipv6" in interface and additional_count > 0:
    #    for additional in interface['ipv6']['additional']:
    #        add = {
    #            "type": "static6",
    #            "control": "auto",
    #            "address": additional['address'],
    #            "netmask": additional['netmask']
    #        }
    #        netcfg['subnets'].append(add)

    # Add config to template
    return netcfg


# Input Metadata and generate private network config part
def generate_private_network_interface(interface):
    interface_name = get_interface_name(interface['mac'])
    if not interface_name:
        raise RuntimeError(
            "Interface: %s could not be found on the system" %
            interface['mac'])

    netcfg = {
        "name": interface_name,
        "type": "physical",
        "mac_address": interface['mac'],
        "subnets": [
            {
                "type": "static",
                "control": "auto",
                "address": interface['ipv4']['address'],
                "netmask": interface['ipv4']['netmask']
            }
        ]
    }

    return netcfg


# vi: ts=4 expandtab
