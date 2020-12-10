# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.addons.component.core import Component


class MetadataBatchImporter(Component):
    """ Import the records directly, without delaying the jobs.

    Import the Amazon Orders, Products
    """

    _name = 'amazon.metadata.batch.importer'
    _inherit = 'amazon.direct.batch.importer'
    _apply_on = [
        'amazon.product.product',
        'amazon.product.product.detail',
        'amazon.res.partner',
    ]
