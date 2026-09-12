### Поверхность: новый прогон, новый джоб и новая дверь транспорта

**Переход одной строкой:**

```
было:  прогонов пятнадцать, джобов на изменении восемнадцать, GraphQL не звался ниоткуда
стало: + arm.yml — джоб arm-probe (pull_request по путям scripts/arm.py, scripts/ghrest.py,
       .github/workflows/arm.yml, и workflow_dispatch); + ghrest.graphql с закрытым списком
       NO_REST; .pipeline.yml — arm-probe: advisory, адресат #196
```

Потребителю, повторяющему шаги у себя, это добавляет **шаг 8d** и требует
ответа по новой проверке в `.pipeline.yml`. Секрет тот же, что у очереди, —
`MERGE_QUEUE_TOKEN`; без него шаг говорит «не настроено», а не краснеет.

### Взведение у площадки сначала замеряют, а потом ему доверяют

Решение [`011`](../docs/decisions/011-merging-is-handed-to-the-platform.md) отдаёт
площадке последнее действие — само слияние — и назвало непроверенным ровно
одно: доходит ли до уплотнения **тело** (`commitHeadline` и `commitBody`).
Поля объявлены входом мутации, но в семье их не передаёт никто, то есть
проверено это не было ни у кого. На непроверенной премисе смена ловила себя
трижды за неделю
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)),
поэтому очередь **не** переключается, пока ответа нет.

Замер устроен так, чтобы ничего не слить:

- под него берётся изменение в состоянии `blocked` — **взвести можно, слить
  нельзя**: между взведением и снятием площадке нечего сливать;
- снятие идёт в `finally`, даже если разбор ответа упал: брошенное взведение
  площадка однажды исполнит сама
  ([109](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/109-every-exit-from-a-transient-state-must-be-terminal.md));
- тело **просят вернуть обратно** в ответе мутации: иначе «поля есть» и «поля
  работают» неотличимы;
- ответ пишется комментарием в эпик #196 — **и удача, и отказ**. Логи прогонов
  агентскому окну недоступны, и замер, оставшийся в логе, замером не является
  ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

### GraphQL получил одну дверь и закрытый список

Правило
[001](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/001-transport-rest-not-graphql.md)
требует REST по умолчанию: у соседей измерено около трёхсот единиц часовой
квоты за операцию GraphQL против одной у REST. Но у взведения авто-мержа
REST-эквивалента нет вовсе, и «нельзя» здесь превратилось бы в частную копию
транспорта.

Поэтому дверь **одна** — `ghrest.graphql`, — и она спрашивает, положено ли
туда идти: операция, которой нет в `NO_REST`, отвергается **до** запроса
([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)).
Каждое имя в списке — утверждение «дешевле нельзя», записанное причиной.

Отдельно разбирается главная ловушка GraphQL: **отказ приходит с кодом 200**,
а лежит в теле полем `errors`. Ответ, прочитанный по коду, выглядел бы удачей
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

#196
