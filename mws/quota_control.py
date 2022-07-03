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
##############################################################################

import logging
from datetime import datetime, timedelta
from math import ceil

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.addons.queue_job.exception import FailedJobError, RetryableJobError

_logger = logging.getLogger(__name__)


class RequestDate(models.Model):
    _name = 'amazon.control.date.request'
    request_id = fields.Many2one('amazon.control.request')
    backend_id = fields.Many2one('amazon.backend', required=True)


class ControlRequest(models.Model):
    _name = 'amazon.control.request'

    request_name = fields.Char(required=True)
    max_quota = fields.Integer(required=True)
    restore_rate = fields.Float(required=True)  # The restore rate quota is expressed in seconds
    max_request_quota_time = fields.Integer()
    max_request_quota_units = fields.Integer()
    units_of_mesaure_quota = fields.Selection(selection=[('sec', 'Seconds'),
                                                         ('min', 'Minutes'),
                                                         ('hor', 'Hours'),
                                                         ('day', 'Days'), ])

    request_date_ids = fields.One2many('amazon.control.date.request', 'request_id')

    @api.model
    def use_quota_if_avaiable(self, request_name, backend_id):
        # TODO: finish the method to control the quota of the methods
        assert request_name
        control = self.search([('request_name', '=', request_name)])
        try:
            assert control
        except AssertionError:
            raise FailedJobError("The action %s doesn't exist on the quota control module (MWS)" % request_name)

        time_now = datetime.now()
        if control.max_request_quota_time > 0:

            max_request_factor = 0

            if control.units_of_mesaure_quota == 'min':
                max_request_factor = 60
            elif control.units_of_mesaure_quota == 'hor':
                max_request_factor = 60 * 60
            elif control.units_of_mesaure_quota == 'day':
                max_request_factor = 60 * 60 * 24

            # Control to hourly quota
            record_count = self.env['amazon.control.date.request'].search_count([('backend_id', '=', backend_id),
                                                                                 ('request_id', '=', control.id),
                                                                                 ('create_date', '>', (time_now - timedelta(
                                                                                     seconds=(max_request_factor - (max_request_factor * 0.1)))).isoformat())],
                                                                                )

            if record_count > control.max_request_quota_time:
                raise UserError(_("The quota of %s is empty (MWS)" % request_name))

            # Control max quota
            seconds_control = control.max_quota * control.restore_rate
            record_count = self.env['amazon.control.date.request'].search_count([('backend_id', '=', backend_id),
                                                                                 ('request_id', '=', control.id),
                                                                                 ('create_date', '>', (time_now - timedelta(
                                                                                     seconds=(seconds_control - (seconds_control * 0.2)))).isoformat())],
                                                                                )

            if record_count > control.max_quota:
                raise UserError(_("The quota of %s is empty (MWS)" % request_name))

        self.env['amazon.control.date.request'].create({'backend_id':backend_id, 'request_id':control.id})

    def throw_retry_exception_for_throttled(self, request_name, backend_id, ignore_retry=True):
        control = self.search([('request_name', '=', request_name)])
        time_now = datetime.now()
        i = 0
        while i < control.max_quota:
            self.env['amazon.control.date.request'].create({'backend_id':backend_id, 'request_id':control.id})
            i += 1

        raise RetryableJobError("MWS API has been an error produced on %s for Request Throttled" % request_name,
                                seconds=ceil(control.restore_rate) + 1,
                                ignore_retry=ignore_retry)
