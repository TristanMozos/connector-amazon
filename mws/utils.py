# -*- coding: utf-8 -*-
"""
Created on Tue Jun 26 15:42:07 2012

Borrowed from https://github.com/timotheus/ebaysdk-python

@author: pierre
"""

import xml.etree.ElementTree as ET
import re
from time import strftime, gmtime


class object_dict(dict):
    """object view of dict, you can
    >>> a = object_dict()
    >>> a.fish = 'fish'
    >>> a['fish']
    'fish'
    >>> a['water'] = 'water'
    >>> a.water
    'water'
    >>> a.test = {'value': 1}
    >>> a.test2 = object_dict({'name': 'test2', 'value': 2})
    >>> a.test, a.test2.name, a.test2.value
    (1, 'test2', 2)
    """

    def __init__(self, initd=None):
        if initd is None:
            initd = {}
        dict.__init__(self, initd)

    def __getattr__(self, item):

        d = self.__getitem__(item)

        if isinstance(d, dict) and 'value' in d and len(d) == 1:
            return d['value']
        else:
            return d

    # if value is the only key in object, you can omit it
    def __setstate__(self, item):
        return False

    def __setattr__(self, item, value):
        self.__setitem__(item, value)

    def getvalue(self, item, value=None):
        return self.get(item, {}).get('value', value)


class xml2dict(object):

    def __init__(self):
        pass

    def _parse_node(self, node):
        node_tree = object_dict()
        # Save attrs and text, hope there will not be a child with same name
        if node.text:
            node_tree.value = node.text
        for (k, v) in node.attrib.items():
            k, v = self._namespace_split(k, object_dict({'value':v}))
            node_tree[k] = v
        # Save childrens
        for child in node.getchildren():
            tag, tree = self._namespace_split(child.tag,
                                              self._parse_node(child))
            if tag not in node_tree:  # the first time, so store it in dict
                node_tree[tag] = tree
                continue
            old = node_tree[tag]
            if not isinstance(old, list):
                node_tree.pop(tag)
                node_tree[tag] = [old]  # multi times, so change old dict to a list
            node_tree[tag].append(tree)  # add the new one

        return node_tree

    def _namespace_split(self, tag, value):
        """
        Split the tag '{http://cs.sfsu.edu/csc867/myscheduler}patients'
        ns = http://cs.sfsu.edu/csc867/myscheduler
        name = patients
        """
        result = re.compile("\{(.*)\}(.*)").search(tag)
        if result:
            value.namespace, tag = result.groups()

        return (tag, value)

    def parse(self, file):
        """parse a xml file to a dict"""
        f = open(file, 'r')
        return self.fromstring(f.read())

    def fromstring(self, s):
        """parse a string"""
        t = ET.fromstring(s)
        root_tag, root_tree = self._namespace_split(t.tag, self._parse_node(t))
        return object_dict({root_tag:root_tree})


def get_timestamp():
    """
        Returns the current timestamp in proper format.
    """
    return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())


def enumerate_keyed_param(param, values):
    """
    Given a param string and a dict of values, returns a flat dict of keyed, enumerated params.
    Each dict in the values list must pertain to a single item and its data points.

    Example:
        param = "InboundShipmentPlanRequestItems.member"
        values = [
            {'SellerSKU': 'Football2415',
            'Quantity': 3},
            {'SellerSKU': 'TeeballBall3251',
            'Quantity': 5},
            ...
        ]

    Returns:
        {
            'InboundShipmentPlanRequestItems.member.1.SellerSKU': 'Football2415',
            'InboundShipmentPlanRequestItems.member.1.Quantity': 3,
            'InboundShipmentPlanRequestItems.member.2.SellerSKU': 'TeeballBall3251',
            'InboundShipmentPlanRequestItems.member.2.Quantity': 5,
            ...
        }
    """
    if not values:
        # Shortcut for empty values
        return {}
    if not param.endswith('.'):
        # Ensure the enumerated param ends in '.'
        param += '.'
    if not isinstance(values, (list, tuple, set)):
        # If it's a single value, convert it to a list first
        values = [values, ]
    for val in values:
        # Every value in the list must be a dict.
        if not isinstance(val, dict):
            # Value is not a dict: can't work on it here.
            raise ValueError((
                "Non-dict value detected. "
                "`values` must be a list, tuple, or set; containing only dicts."
            ))
    params = {}
    for idx, val_dict in enumerate(values):
        # Build the final output.
        params.update({
            '{param}{idx}.{key}'.format(param=param, idx=idx + 1, key=k):v
            for k, v in val_dict.items()
        })
    return params
