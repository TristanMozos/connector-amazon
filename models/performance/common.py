# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2020 Halltic eSolutions S.L. (https://www.halltic.com)
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
##############################################################################

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
