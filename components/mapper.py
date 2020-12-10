# -*- coding: utf-8 -*-
# © 2013 Guewen Baconnier,Camptocamp SA,Akretion
# © 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.addons.component.core import AbstractComponent


class AmazonImportMapper(AbstractComponent):
    _name = 'amazon.import.mapper'
    _inherit = ['base.amazon.connector', 'base.import.mapper']
    _usage = 'import.mapper'


class AmazonExportMapper(AbstractComponent):
    _name = 'amazon.export.mapper'
    _inherit = ['base.amazon.connector', 'base.export.mapper']
    _usage = 'export.mapper'


def normalize_datetime(field):
    """Change a invalid date which comes from Amazon, if
    no real date is set to null for correct import to
    OpenERP"""

    def modifier(self, record, to_attr):
        if record[field] == '0000-00-00 00:00:00':
            return None
        return record[field]

    return modifier
