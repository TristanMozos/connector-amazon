# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

import time
from odoo import models, fields, api
from odoo.addons.component.core import Component
from odoo.addons.queue_job.job import job

_logger = logging.getLogger(__name__)


class AmazonFeed(models.Model):
    _name = 'amazon.feed'
    _inherit = 'amazon.binding'
    _description = 'Amazon Feed'

    @job(default_channel='root.amazon')
    @api.model
    def import_batch(self, backend, filters=None):
        _super = super(AmazonFeed, self)
        return _super.import_batch(backend, filters=filters)


class AmazonFeedAdapter(Component):
    _name = 'amazon.feed.adapter'
    _inherit = 'amazon.adapter'
    _apply_on = 'amazon.feed'

    @api.multi
    def submit_report(self, report_name, filters):
        return self._call(method=report_name, arguments=filters)

    def get_report(self, arguments):
        try:
            assert arguments
            return self._call(method=arguments.pop('method'), arguments=arguments['report_id'])
        except AssertionError:
            _logger.error('There aren\'t parameters for %s', 'get_report')
            raise
