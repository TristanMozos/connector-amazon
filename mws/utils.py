# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2022 Halltic Tech S.L. (https://www.halltic.com)
#                  Tristán Mozos <tristan.mozos@halltic.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Basic interface to Amazon MWS on Odoo
# Forked and modified code of https://github.com/czpython/python-amazon-mws
##############################################################################

from __future__ import absolute_import
from functools import wraps
import re
import datetime
import json
import xml.etree.ElementTree as ET

try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote


class ObjectDict(dict):
    """Extension of dict to allow accessing keys as attributes.

    Example:
    >>> a = ObjectDict()
    >>> a.fish = 'fish'
    >>> a['fish']
    'fish'
    >>> a['water'] = 'water'
    >>> a.water
    'water'
    """

    def __init__(self, initd=None):
        if initd is None:
            initd = {}
        dict.__init__(self, initd)

    def __getattr__(self, item):
        """Allow access to dict keys as though they were attributes."""
        return self.__getitem__(item)

    def __setattr__(self, item, value):
        """Allows setting dict keys like attributes, opposite of `__getattr__`."""
        self.__setitem__(item, value)

    def _value_or_node(self, node):
        """If `node` contains only a single 'value' key, returns the raw value.
        Otherwise, returns the node unchanged.
        """
        if isinstance(node, self.__class__) and "value" in node and len(node) == 1:
            return node["value"]
        return node

    def __getitem__(self, key):
        """Returns single-value nodes as the raw value, and all else unchanged."""
        node = super().__getitem__(key)
        return self._value_or_node(node)

    def __setstate__(self, item):
        return False

    def __iter__(self):
        """Nodes are iterable be default, even with just one child node.

        Returns non-list nodes wrapped in an iterator, so they can be iterated
        and return the child node.
        """
        # If the parser finds multiple sibling nodes by the same name
        # (under the same parent node), that node will return a list of DotDicts.
        # However, if the same node is returned with only one child in other responses,
        # downstream code may expect the list, but iterating the single node will
        # throw an error.
        # So, when iteration is required, we return single nodes as an iterator
        # wrapping that single instance.
        if not isinstance(self, list):
            return iter([self])
        return self

    def getvalue(self, key, default=None):
        """Access a node like `dict.get`, including default values."""
        try:
            return self.__getitem__(key)
        except KeyError:
            return default


class XML2Dict(object):
    def __init__(self):
        pass

    def _parse_node(self, node):
        node_tree = ObjectDict()
        # Save attrs and text, hope there will not be a child with same name
        if node.text:
            node_tree.value = node.text
        for key, val in node.attrib.items():
            key, val = self._namespace_split(key, ObjectDict({"value":val}))
            node_tree[key] = val
        # Save children
        for child in node:
            tag, tree = self._namespace_split(child.tag, self._parse_node(child))
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
        result = re.compile(r"\{(.*)\}(.*)").search(tag)
        if result:
            value.namespace, tag = result.groups()

        return (tag, value)

    def parse(self, filename):
        """
        Parse XML file to a dict.
        """
        file_ = open(filename, "r")
        return self.fromstring(file_.read())

    def fromstring(self, str_):
        """
        Parse a string
        """
        text = ET.fromstring(str_)
        root_tag, root_tree = self._namespace_split(text.tag, self._parse_node(text))
        return ObjectDict({root_tag:root_tree})


def enumerate_param(param, values):
    """
    Builds a dictionary of an enumerated parameter, using the param string and some values.
    If values is not a list, tuple, or set, it will be coerced to a list
    with a single item.

    Example:
        enumerate_param('MarketplaceIdList.Id', (123, 345, 4343))
    Returns:
        {
            MarketplaceIdList.Id.1: 123,
            MarketplaceIdList.Id.2: 345,
            MarketplaceIdList.Id.3: 4343
        }
    """
    if not values:
        # Shortcut for empty values
        return {}
    if not isinstance(values, (list, tuple, set)):
        # Coerces a single value to a list before continuing.
        values = [
            values,
        ]
    if not param.endswith("."):
        # Ensure this enumerated param ends in '.'
        param += "."
    # Return final output: dict comprehension of the enumerated param and values.
    return {"{}{}".format(param, idx + 1):val for idx, val in enumerate(values)}


def enumerate_params(params=None):
    """
    For each param and values, runs enumerate_param,
    returning a flat dict of all results
    """
    if params is None or not isinstance(params, dict):
        return {}
    params_output = {}
    for param, values in params.items():
        params_output.update(enumerate_param(param, values))
    return params_output


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
    if not param.endswith("."):
        # Ensure the enumerated param ends in '.'
        param += "."
    if not isinstance(values, (list, tuple, set)):
        # If it's a single value, convert it to a list first
        values = [
            values,
        ]
    for val in values:
        # Every value in the list must be a dict.
        if not isinstance(val, dict):
            # Value is not a dict: can't work on it here.
            raise ValueError(
                (
                    "Non-dict value detected. "
                    "`values` must be a list, tuple, or set; containing only dicts."
                )
            )
    params = {}
    for idx, val_dict in enumerate(values):
        # Build the final output.
        params.update(
            {
                "{param}{idx}.{key}".format(param=param, idx=idx + 1, key=k):v
                for k, v in val_dict.items()
            }
        )
    return params


def unique_list_order_preserved(seq):
    """
    Returns a unique list of items from the sequence
    while preserving original ordering.
    The first occurrence of an item is returned in the new sequence:
    any subsequent occurrences of the same item are ignored.
    """
    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]


def dt_iso_or_none(dt_obj):
    """
    If dt_obj is a datetime, return isoformat()
    TODO: if dt_obj is a string in iso8601 already, return it back
    Otherwise, return None
    """
    # If d is a datetime object, format it to iso and return
    if isinstance(dt_obj, datetime.datetime):
        return dt_obj.isoformat()

    # TODO: if dt_obj is a string in iso8601 already, return it

    # none of the above: return None
    return None


def next_token_action(action_name):
    """
    Decorator that designates an action as having a "...ByNextToken" associated request.
    Checks for a `next_token` kwargs in the request and, if present, redirects the call
    to `action_by_next_token` using the given `action_name`.

    Only the `next_token` kwarg is consumed by the "next" call:
    all other args and kwargs are ignored and not required.
    """

    def _decorator(request_func):
        @wraps(request_func)
        def _wrapped_func(self, *args, **kwargs):
            next_token = kwargs.pop("next_token", None)
            if next_token is not None:
                # Token captured: run the "next" action.
                return self.action_by_next_token(action_name, next_token)
            return request_func(self, *args, **kwargs)

        return _wrapped_func

    return _decorator


def remove_xml_namespaces(data):
    """Return namespaces found in the XML `data`, in either str or bytes format."""
    pattern = r'xmlns(:ns2)?="[^"]+"|(ns2:)|(xml:)'
    replacement = ""
    if not isinstance(data, str):
        # Encode the pattern and substitute to use them on bytes data.
        pattern = pattern.encode()
        replacement = replacement.encode()
    return re.sub(pattern, replacement, data)


def mws_utc_now():
    """Returns the current UTC time, as expected by MWS.
    Note that we set microseconds to 0 automatically with this method:
    if you want the true UTC datetime, just run `datetime.datetime.utcnow()`.
    """
    return datetime.datetime.utcnow().replace(microsecond=0)


def remove_empty_param_keys(params):
    """Returns a copy of ``params`` dict where any key with a value of ``None``
    or ``""`` (empty string) are removed.
    """
    return {k:v for k, v in params.items() if v is not None and v != ""}


def clean_params_dict(params):
    """Clean multiple param values in a dict, returning a new dict
    containing the original keys and cleaned values.
    """
    cleaned_params = dict()
    for key, val in params.items():
        try:
            cleaned_params[key] = clean_value(val)
        except ValueError as exc:
            from mws.mws import MWSError

            raise MWSError(str(exc)) from exc
    return cleaned_params


def clean_value(val):
    """Attempts to clean a value so that it can be sent in a request."""
    if isinstance(val, (dict, list, set, tuple)):
        raise ValueError("Cannot clean parameter value of type %s" % str(type(val)))

    if isinstance(val, (datetime.datetime, datetime.date)):
        return clean_date(val)
    if isinstance(val, bool):
        return clean_bool(val)

    # For all else, assume a string, and clean that.
    return clean_string(str(val))


def clean_string(val):
    """Passes a string value through `urllib.parse.quote` to clean it.
    Safe characters permitted: -_.~
    """
    return quote(val, safe="-_.~")


def clean_bool(val):
    """Converts a boolean value to its JSON string equivalent."""
    if val is not True and val is not False:
        raise ValueError("Expected a boolean, got %s" % val)
    return json.dumps(val)


def clean_date(val):
    """Converts a datetime.datetime or datetime.date to ISO 8601 string.
    Further passes that string through `urllib.parse.quote`.
    """
    return clean_string(val.isoformat())


# DEPRECATION: these are old names for these objects, which have been updated
# to more idiomatic naming convention. Leaving these names in place in case
# anyone is using the old object names.
# TODO: remove in 1.0.0
object_dict = ObjectDict
xml2dict = XML2Dict
