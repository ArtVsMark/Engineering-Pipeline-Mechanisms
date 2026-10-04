# Engineering Pipeline Mechanisms

> **Читатель:** посетитель — что это такое и стоит ли брать.

[![Состояние: Python и его версия, ОС linux / windows / mac, покрытие, выпуск, версия проекта](https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/.github/badges/python.svg)](.github/workflows/ci.yml) [![правил каталога держится машиной](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/.github/badges/rules.json&cacheSeconds=300)](.rules/bindings.json) [![доля машинного соблюдения семьи, закрытая общими механизмами](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/.github/badges/family.json&cacheSeconds=300)](docs/decisions/016-family-completeness-outranks-the-release-number.md) [![запускаемых механизмов гоняется процессом](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/.github/badges/scripts.json&cacheSeconds=300)](scripts/)

**Механизмы конвейера: скелет один для всех проектов, наполнение своё.**
Открытие изменения, гейты, очередь и слияние, здоровье общей ветки, выпуск —
одними и теми же файлами с одними и теми же именами шагов. Своё у проекта —
чем шаг наполнен, и объявляется это данными, а не правкой прогона.

> Правила — в каталоге [Engineering-Incidents-Playbook](https://github.com/ArtVsMark/Engineering-Incidents-Playbook).
> Неофициально, к Anthropic отношения не имеет.

## Зачем

Пять проектов одной семьи держат конвейер копиями. Копии разошлись — не в
деталях, а полностью: одноимённые файлы отличаются кратно, и ни одна сверенная
пара не совпала. Замер, из которого это взято, — в
[`docs/use/pipeline.md`](docs/use/pipeline.md); он с датой, и второй раз здесь не
приводится, чтобы не разойтись с первым
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

Расхождение стоит не аккуратности, а простоев: обязательная проверка, которой
не выдаёт ни один прогон, останавливает слияния целиком — и не краснеет нигде,
потому что краснеть нечему.

## Граница: чем это не является

**Каталог держит правила. Этот проект держит механизмы.** Что живёт здесь, а
что остаётся дома у проекта, и чем это проверяется — в договоре,
[«Граница проекта»](docs/use/pipeline.md#граница-проекта).

Это **не сборник заготовок для копирования**: подключение к общим механизмам
идёт версией, к которой потребитель прибит, а не переносом файлов руками.
Заготовки для того, кому механизмы недоступны, лежат у каталога — в
[`templates/`](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/tree/main/templates).

## Что можно взять

Девять шагов конвейера — вызовом по адресу с версией, а не копией файла к себе.
Копия — ровно та беда, из-за которой передача и затевалась; замер копий по
проектам семьи — в [договоре](docs/use/pipeline.md).

`.github/workflows/`: [`step-lint.yml`](.github/workflows/step-lint.yml) ·
[`step-pr-meta.yml`](.github/workflows/step-pr-meta.yml) ·
[`step-journal.yml`](.github/workflows/step-journal.yml) ·
[`step-attribution.yml`](.github/workflows/step-attribution.yml) ·
[`step-pipeline.yml`](.github/workflows/step-pipeline.yml) ·
[`step-contract.yml`](.github/workflows/step-contract.yml) ·
[`step-debt.yml`](.github/workflows/step-debt.yml) ·
[`step-window-lifetime.yml`](.github/workflows/step-window-lifetime.yml) ·
[`step-rulebook-fresh.yml`](.github/workflows/step-rulebook-fresh.yml)

Управляющие механизмы — тем же вызовом по тегу, но своим прогоном со своими
событиями, а не джобом в `ci.yml`: [`step-work-plan.yml`](.github/workflows/step-work-plan.yml)
(план работ) · [`step-automerge.yml`](.github/workflows/step-automerge.yml)
(очередь и слияние) · [`step-main-red.yml`](.github/workflows/step-main-red.yml)
(дежурный по общей ветке) · [`step-stuck.yml`](.github/workflows/step-stuck.yml)
(застрявшее) · [`step-hail.yml`](.github/workflows/step-hail.yml) (оклик) ·
[`step-drift.yml`](.github/workflows/step-drift.yml) (дрейф внешних входов).
Очереди, обходу и оклику токен владельца `MERGE_QUEUE_TOKEN` передаётся
вызовом явно, по имени: секретов вызывающего общий шаг не видит. Вынос
остальных ведёт #993.

**Заготовку вызова собирает заход `scripts/onboard.py`**, а не вы руками:
он печатает готовые джобы с прибивкой к последнему выпуску и заготовку ответа
по каждой проверке. Кто уже подключён и что у него обойдено — печатает
`scripts/consumers.py`, читая это в их деревьях, а не ведя реестр за них.

**Как подключиться, что делает каждый шаг и куда идти, если что-то пошло не
так, — [`docs/use/onboarding.md`](docs/use/onboarding.md).** Здесь этого нет намеренно:
витрину читает пришедший решить, стоит ли брать, а подключение читает уже
взявший, и это разные читатели
([021](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/021-split-docs-by-reader.md)).

**Чего ещё нет, и это названо, а не умолчано:** исходящего сигнала потребителям
при смене версии контракта. Потребительская половина контракта связи и сверка
потребителей построены (`.rules/consumers.json`, `scripts/consumers.py`), но
подключённых потребителей, кроме нас самих, пока нет, и слать сигнал некому
(075).

Названо это здесь потому, что отсутствующий механизм и молчащий механизм
снаружи неотличимы
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
Что именно ещё не доказано прогоном — таблицей в [`docs/dev/gaps.md`](docs/dev/gaps.md).

Значки в шапке собраны прогоном, а не вписаны руками: `badges.yml` пересчитывает
`facts.json` и весь набор значков на каждое слияние и толкает их в отдельную
ветку `badges` — производное не коммитится туда, где живёт источник, и не
конфликтует на каждом слиянии
([160](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/160-derived-artifacts-live-off-the-branch.md)).
Строка о нём ушла из таблицы пробелов после первого прогона публикации, а не
после написания кода
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

Первый значок — единый, общий для всей семьи: «Python» и версии языка,
каждая окрашена исходом своего прогона на `main` — 3.14 и ОС прогоном `ci`,
3.15 предрелизным `python-next`, — за ними покрытие, выпуск и версия проекта.
У проверок зелёный — пройдено, красный — нет, серый — не проверялось:
windows и mac у проекта серые, потому что их не гоняют. Зона выпуска серая
по другой причине: на PyPI механизмы не публикуются. Она показывает два
старших числа выпуска, полный тег — на странице выпусков. Рисует значок
действие каталога `python-badge` с тега, а не копия здесь: копия разошлась
бы с каталогом при первой его правке
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

Файлом фактов `facts.json` открыт канал соседям и каталогу правил: версия контракта,
сколько правил каталога проект держит и чем именно, состав классов проверок —
всё читается по адресу raw ветки `badges`, без клона дерева. Факты о проекте
публикует сам проект
([174](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/174-facts-about-a-project-are-published-by-it.md)).

Порядок подключения потребителей и признаки готовности каждого этапа —
[`docs/dev/roadmap.md`](docs/dev/roadmap.md).

## Что читать

| Документ | Отвечает на вопрос |
|---|---|
| [`docs/use/pipeline.md`](docs/use/pipeline.md) | **из чего** конвейер состоит: шаги, файлы, правила формы |
| [`docs/agent/behaviour.md`](docs/agent/behaviour.md) | **что происходит, когда**: три контура, заморозка, предел попыток |
| [`docs/dev/roadmap.md`](docs/dev/roadmap.md) | **в каком порядке** это строится и по чему видно готовность |
| [`AGENTS.md`](AGENTS.md) | что проект требует от агента — ядро |
| [`CLAUDE.md`](CLAUDE.md) | чем агентское окно отличается от любого другого агента |
| [`docs/README.md`](docs/README.md) | **кому что читать**: все документы по читателю |

Разделение не по темам, а по читателю: одному нужен состав, другому поведение,
и второе из первого не выводится
([021](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/021-split-docs-by-reader.md)).

## Как это развивается

Проект — **свой первый потребитель**. Механизм, которым не пользуется его
автор, находит свои дыры на чужом проекте и в худший момент
([155](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/155-a-template-you-dont-use-drifts.md)).
Поэтому собственная обвязка идёт раньше выноса общих механизмов наружу, и
11.09.2026 это стало **порядком работ, а не пожеланием**. Условие наступило и
**померено** 19.09.2026: [#196](../../issues/196) закрыт, числа — в записи
[`032`](docs/decisions/032-the-handover-is-unblocked-by-measurement.md). Вынос
идёт поштучно, по проекту семьи на подзадачу эпика
[#782](../../issues/782); прежний эпик передачи [#547](../../issues/547) слит с ним.

Правило, родившееся здесь, уезжает в каталог вместе со своим инцидентом:
формулировка остаётся тут, разбор живёт там
([080](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/080-every-new-rule-goes-into-the-catalogue.md)).

## Второй исход

Перенос может и не окупиться, и этот исход записан заранее: условие остановки —
в [плане развития](docs/dev/roadmap.md#второй-исход).
