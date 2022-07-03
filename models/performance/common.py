# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# This project is based on connector-magneto, developed by Camptocamp SA

import logging

from odoo import models, fields, api
from odoo.addons.component.core import Component
from odoo.addons.queue_job.job import job

_logger = logging.getLogger(__name__)


class AmazonPartnerFeedback(models.Model):
    _name = 'amazon.res.partner.feedback'
    _inherit = 'amazon.binding'
    _description = 'Amazon Partner Feedback'

    amazon_sale_id = fields.Many2one('amazon.sale.order')
    feedback_date = fields.Date('Feedback date')
    qualification = fields.Selection([('0', 'Very Low'), ('1', 'Low'), ('2', 'Normal'), ('3', 'High'), ('4', 'Very High')], string='Qualification')
    respond = fields.Char('Respond')
    message = fields.Char('Message')

    @job(default_channel='root.amazon')
    @api.model
    def import_record(self, backend, external_id):
        _super = super(AmazonPartnerFeedback, self)
        return _super.import_record(backend, external_id)


class AmazonPartnerFeedbackAdapter(Component):
    _name = 'amazon.res.partner.feedback.adapter'
    _inherit = 'amazon.adapter'
    _apply_on = 'amazon.res.partner.feedback'