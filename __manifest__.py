{
    "name": "Bank Statement Import (Rep Dominicana)",
    "summary": """
        Este módulo extiende las funcionalidades del módulo de importación de extractos bancarios para adactarlo 
        a los formatos utilizados en Rep Dominicana en los extractos bancarios.
        """,
    "author": "Luis Fernandez",
    "category": "Localization",
    "depends": ['account_accountant'],
    "data": [
        'security/ir.model.access.csv',
        'views/account_journal_view.xml',
        'wizard/account_bank_statement_import_views.xml',
        'wizard/account_bank_statement_faild_import_views.xml',
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
