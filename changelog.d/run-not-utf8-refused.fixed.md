Прогон, ответ проекта или `CONTRACT_VERSION` не в UTF-8 больше не роняет сверку семьи и чтение `.pipeline.yml` трассой `UnicodeDecodeError`: `run_of`, `load`, `span`, `contract_of`, `fragment_form` и `family_check.steps_links` читают файл одним `pipeline_checks.file_text` и отказывают `BadPolicy` с причиной, а `family_check.pinned` называет такой прогон непрочитанным. `span` заодно называет битый YAML отказом, а не трассой.

#1567
