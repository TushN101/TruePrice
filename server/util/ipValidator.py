

"""

Validates the IP address returns boolean output

"""

import ipaddress

def validateIp(ip_str: str):
    try:
        _ = ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False
