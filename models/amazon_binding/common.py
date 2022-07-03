# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2022 Halltic T S.L. (https://www.halltic.com)
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

from odoo import api, models, fields
from odoo.addons.queue_job.exception import FailedJobError, RetryableJobError
from odoo.addons.queue_job.job import Job


class AmazonBinding(models.AbstractModel):
    """ Abstract Model for the Bindings.

    All the models used as bindings between Amazon and Odoo
    (``amazon.res.partner``, ``amazon.product.product``, ...) should
    ``_inherit`` it.
    """
    _name = 'amazon.binding'
    _inherit = 'external.binding'
    _description = 'Amazon Binding (abstract)'

    # odoo_id = odoo-side id must be declared in concrete model
    backend_id = fields.Many2one(
        comodel_name='amazon.backend',
        string='Amazon Backend',
        required=True,
        ondelete='restrict',
    )
    # fields.Char because 0 is a valid Amazon ID
    external_id = fields.Char(string='ID on Amazon')

    _sql_constraints = [
        ('amazon_uniq', 'unique(backend_id, external_id)',
         'A binding already exists with the same Amazon ID.'),
    ]

    @api.model
    def import_batch(self, backend, filters=None):
        """ Prepare the import of records modified on Amazon """
        if filters is None:
            filters = {}

        try:
            with backend.work_on(self._name) as work:
                importer = work.component(usage='batch.importer')
                return importer.run(filters=filters)
        except Exception as e:
            return e

    @api.model
    def export_batch(self, backend, filters=None):
        """ Prepare the export of records on Amazon """
        if filters is None:
            filters = {}
        try:
            with backend.work_on(self._name) as work:
                exporter = work.component(usage='batch.exporter')
                return exporter.run(filters=filters)
        except Exception as e:
            return e

    @api.model
    def import_record(self, backend, external_id, force=False):
        """ Import a Amazon record """
        exception = None
        with backend.work_on(self._name) as work:
            try:
                importer = work.component(usage='record.importer')
                return importer.run(external_id, force=False)
            except Exception as e:
                exception = e

        if exception:
            raise exception

    def export_record(self, backend, internal_id):
        """ Export a record on Amazon """
        exception = None
        with backend.work_on(self._name) as work:
            exporter = work.component(usage='record.exporter')
            try:
                return exporter.run(internal_id)
            except Exception as e:
                exception = e

        if exception:
            raise exception
