# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.addons.component.core import Component


class AmazonBindingBackendListener(Component):
    _name = 'amazon.binding.amazon.backend.listener'
    _inherit = 'base.connector.listener'
    _apply_on = ['amazon.backend']
