# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# This project is based on connector-magneto, developed by Camptocamp SA

from odoo.addons.component.core import Component


class AmazonModelBinder(Component):
    """ Bind records and give odoo/amazon ids correspondence

    Binding models are models called ``amazon.{normal_model}``,
    like ``amazon.res.partner`` or ``amazon.product.product``.
    They are ``_inherits`` of the normal models and contains
    the Amazon ID, the ID of the Amazon Backend and the additional
    fields belonging to the Amazon instance.
    """
    _name = 'amazon.binder'
    _inherit = ['base.binder', 'base.amazon.connector']
    _apply_on = [
        'amazon.product.product',
        'amazon.product.product.detail',
        'amazon.sale.order',
        'amazon.sale.order.line',
        'amazon.res.partner',
        'amazon.res.partner.feedback',
    ]
