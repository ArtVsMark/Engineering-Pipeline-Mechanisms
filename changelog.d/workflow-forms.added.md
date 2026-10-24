### Гейт опасных форм прогонов в шаге `pipeline`

Шаг «в прогонах нет опасных форм» (`scripts/check_workflow_forms.py`)
краснеет на `actions/checkout` в джобе с правом записи без явного
`persist-credentials` (или с `true` без причины), на `pull_request_target`,
джобе без `permissions`, `write-all` и стороннем действии не на полном `sha`.
Своё семейное — по тегу выпуска. Исключения с причиной — в
`.rules/workflow-forms.json`; исключение без места краснеет.

#1430
