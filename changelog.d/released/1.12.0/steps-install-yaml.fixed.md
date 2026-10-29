Джобы `map`, `findings`, `sweep` и `late-queue` общего шага взгляда и шаг `schedules-seen` ставят `pyyaml`: с #1641 их скрипты импортируют `yaml` через `pipeline_checks` и падали на первой строке, а шаг называл отказ предупреждением — реестр находок не пополнялся и не убирался. Гейт `tests/test_steps_install_what_they_import.py` импортирует каждый скрипт джоба с закрытым `yaml`.

#193
