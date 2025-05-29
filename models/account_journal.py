from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def _get_bank_entity_to_import_statement(self):
        return [
            ('BHD', 'BHD'),
            ('BPD', 'BPD'),
            ('BRD', 'BRD'),
        ]

    l10n_do_bank = fields.Selection(
        string=_('Bank'),
        selection=_get_bank_entity_to_import_statement,
        defaault='undefined',
        help=_('Bank entity to import bank statements'),
    )

    l10n_do_invert_ammounts = fields.Boolean(
        string=_('Is a credit card?'),
        default=False,
        help=_('Mark if this journaal is for a credit card'),
    )

    l10n_do_statement_file_type = fields.Selection(
        string=_('Statement file type'),
        selection=[('CSV', 'CSV')],
        help=_('Statement file type to import bank statements'),
    )

    def import_statement(self): 
        if not self.l10n_do_bank or not self.l10n_do_statement_file_type:
            raise UserError(_("You must select a bank entity and a statement file type."))
        return {
            'name': _('Upload Bank Statements'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement.import',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'journal_id': self.id, 
                'default_is_for_credit_card': self.l10n_do_invert_ammounts
            },
        }