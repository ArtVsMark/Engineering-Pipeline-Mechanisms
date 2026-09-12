> **Потребителю безразлично:** меняется один комментарий в механизме — имена полей взведения теперь подкреплены датой замера, а не памятью автора. Поведение то же.

Замер 12.09.2026 на взведённом #236: площадка отдаёт `commit_message`,
`commit_title`, `enabled_by`, `merge_method`. То есть имена, которые
`held_body` читает, верны; способ слияния — `squash`; а **взвёл владелец**, а не
приложение
([131](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/131-no-writes-from-a-cloud-session.md)).

Проверки эта запись не приносит намеренно: ловить нечего — отказ на неверной
форме ответа уже проверен отказом (`test_an_arming_without_body_fields_is_a_refusal`),
а датированный замер это след, а не поведение
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

#196
