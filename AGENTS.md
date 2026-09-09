# Механизмы конвейера — ядро для любого агента

> **Читатель:** агент — что проект требует от любого агента.

Это ядро: что требуется от **любого** агента, работающего в этом репозитории,
независимо от того, чем он запущен. Надстройка для агентского окна Claude
Code — [`CLAUDE.md`](CLAUDE.md); человеку со стороны — [`README.md`](README.md).
Разные читатели — разные документы
([021](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/021-split-docs-by-reader.md)).

**Договор — канон, свод — триггеры.** Устройство конвейера описано в
[`docs/pipeline.md`](docs/pipeline.md), поведение — в
[`docs/behaviour.md`](docs/behaviour.md), порядок работ — в
[`docs/roadmap.md`](docs/roadmap.md). Здесь ни одно их утверждение не
повторяется: пересказ заводит второй источник, и первая же правка разводит их
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[029](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/029-triggers-and-canon.md)).

**Здесь действуют правила каталога, а не только названное ниже.** Каталог —
[Engineering-Incidents-Playbook](https://github.com/ArtVsMark/Engineering-Incidents-Playbook),
указатель — [`rules/README.md`](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/README.md).
Ядро называет поимённо лишь то, что нарушается чаще всего; остальное окно
обязано найти само, и «в своде не было» причиной не считается
([134](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/134-a-window-reopens-only-after-the-rulebook-exists.md)).

**Чужое «почему» — ссылка, а не копия**
([153](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/153-foreign-why-is-a-link-not-a-copy.md)).
Инцидент, из которого выросло правило, живёт в каталоге. Здесь — формулировка
и адрес.

## 🚦 Критические запреты

```
❌ НЕ писать в main напрямую — только изменением через ветку
❌ НЕ открывать изменение учётными данными агента: автором в общей ветке
   станет приложение, и переписать это нечем (131)
❌ НЕ переносить механизм сюда до того, как принято решение, от которого он
   зависит, — перенос до решения фиксирует в общем модуле текущий разнобой
❌ НЕ класть сюда файл про предмет одного проекта: мерка не «похоже», а
   «реализует общее правило» (граница — docs/pipeline.md)
❌ НЕ пересказывать договор в своде и в README — только ссылка (022)
❌ НЕ вписывать числа в прозу без маркера и сборки, которая их переписывает
   (005, 127); замер с названной датой числом в прозе не считается
❌ НЕ править версию руками ни в одном файле (035)
❌ НЕ пушить в ветку чужого изменения — её ведёт своё окно
```

Номера в блоке — адреса, а не память: [005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md) · [022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md) · [035](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/035-version-is-never-edited-by-hand.md) · [127](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/127-a-number-in-prose-needs-a-guarded-marker.md) · [131](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/131-no-writes-from-a-cloud-session.md). Внутри блока ссылка не
работает, поэтому она стоит здесь, а не опущена.

Часть этих запретов **машинно не проверяется**: гейт видит имя ветки, но не
намерение. Они записаны явно именно поэтому, а не потому что «и так понятно»
([057](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/057-unmechanizable-rules-are-named-explicitly.md)).

## 🕳 Чего в проекте ещё нет

Раздел существует, чтобы окно не предполагало механизмов, которых здесь нет:
отсутствующий гейт и молчащий гейт снаружи неотличимы, и **пробел называется, а
не выравнивается**
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
Строка уходит отсюда, когда механизм появился и **подтверждён прогоном**, а не
когда написан
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

| чего нет или что не доказано | следствие для окна | задача |
|---|---|---|
| **подтверждения прогоном** у гейтов `gates.yml` | механизмы написаны и проверены локально, но зелёного на площадке ещё не было: до первого прогона это гипотеза, а не гарантия | [#11](../../issues/11) |
| гейта перед пушем **одной командой** | проверки зовутся по одной и руками; то, что надо помнить, пропускают под давлением задачи | [#11](../../issues/11) |
| секрета `OWNER_TOKEN` | `open-pr` предупреждает и не открывает изменение — открывать придётся руками, и автором станет тот, кто открыл | [#12](../../issues/12) |
| сверки контекста с защитой ветки | `required-context` без токена владельца говорит «не выполнено»; расхождение имени с настройкой не ловится ничем другим | [#11](../../issues/11) |
| ответа по **129** записям каталога | они несут `unreviewed`: это объявленная очередь, а не решение | [#9](../../issues/9) |
| значков, метрик и публикации | производное **не коммитится в общую ветку**: значки и сводки живут в отдельной ветке `badges`, как у соседей по семье | [#2](../../issues/2) |
| очереди, слияния и здоровья общей ветки | контуры 2 и 3 договора не реализованы: механизма нет до решений [#3](../../issues/3) и [#4](../../issues/4) | [#2](../../issues/2) |
| кода общих механизмов | этап 1 не закрыт: перенос до решения фиксирует в общем модуле текущий разнобой | [#2](../../issues/2) |

## 🔌 Транспорт к площадке

**Самый дешёвый из доступных, и цена операции проверяется до того, как на ней
построен конвейер**
([001](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/001-transport-rest-not-graphql.md),
[017](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/017-measure-quota-do-not-guess.md)).
Разница между транспортами бывает трёхсоткратной, и обнаруживается она на
конвейере, который уже написан.

Общий транспортный слой — предмет фазы 2 эпика [#2](../../issues/2), а не
здешнего свода: пока его нет, каждое окно ходит тем, что ему доступно, и
**называет чем** в описании изменения.

## 🌿 Ветка, изменение, коммит

**Ветка режется от последнего зелёного коммита общей ветки**, а не от головы.
Почему — [`docs/behaviour.md`](docs/behaviour.md), контур 1.

**Имя ветки — по задаче, а не по окну**
([189](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/189-a-branch-is-named-by-its-task-not-its-window.md)),
и префикс имени работает переключателем поведения конвейера
([003](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/003-branch-name-is-a-switch.md)).
Пока [#12](../../issues/12) не сделан, **префикс не переключает ничего** — это
объявленный пробел, а не работающий механизм.

**Одна тема на изменение**
([132](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/132-one-change-carries-one-topic.md)),
границу задаёт пересечение файлов, а не число задач
([133](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/133-file-overlap-sets-the-boundary.md)).

**Автор коммита — человек, агент — соавтор.** Трейлеры живут в хвостовом
блоке, а не в любой строке сообщения
([156](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/156-trailers-live-in-the-tail-not-in-the-prose.md)).
Подпись сверяется **до слияния**: площадка собирает итоговый коммит сама, а
историю общей ветки не переписать
([123](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/123-attribution-is-verified-on-the-final-history.md)).

## 🎯 Открытая работа

Окно не выбирает, чем заняться: источники упорядочены, и **первый непустой и
есть план**
([091](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/091-work-sources-are-ordered-first-non-empty-wins.md)).
Порядок и состояния — [`docs/behaviour.md`](docs/behaviour.md), контур 1.

Трекер — единственный источник статусов. В файлы дерева он не дублируется, и
**журнала работ в действующих документах нет**
([024](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/024-no-worklog-in-active-docs.md)):
что сделано — видно по закрытым задачам и журналу изменений, а не по разделу
«история» в своде.

## 📓 Новое правило — в общий каталог

Правило, выстраданное здесь, записывается в
[каталог](https://github.com/ArtVsMark/Engineering-Incidents-Playbook) **тем же
заходом**, что и правка свода: здесь остаётся формулировка и ссылка, инцидент и
границы применимости живут там
([080](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/080-every-new-rule-goes-into-the-catalogue.md)).
Канал предложений — `.rules/proposals.json` ([#9](../../issues/9)).

Не идёт в каталог то, у чего не нашлось инцидента: это предпочтение, а не
правило.

**Обобщение — по третьему случаю.** Один особый случай потребителя не правит
общий механизм: шов вводится рано, обобщение поздно
([093](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/093-seam-early-generalisation-late.md)).

## ✅ Перед толчком

Гейта одной командой здесь **пока нет** — см. раздел о пробелах. До
[#11](../../issues/11) проверяется руками, и проверяется ровно это:

- [ ] изменение несёт **одну** тему, и она названа в заголовке;
- [ ] ни одно утверждение не продублировало договор — только ссылка;
- [ ] ссылка на правило каталога ведёт в существующий файл, а не в
      придуманный номер: **номер проверяется открытием**, а не памятью;
- [ ] число в прозе либо снабжено маркером и сборкой, либо это замер с
      названной датой, либо его нет;
- [ ] трейлеры авторства — в хвостовом блоке, автор — человек;
- [ ] пробел, который изменение создало или закрыло, отражён в разделе «чего
      ещё нет».

Гейт, не нашедший предмета проверки, обязан падать, а не зеленеть
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)) —
это относится и к списку выше, когда он станет прогоном.
