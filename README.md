# Engineering Pipeline Mechanisms

> **Читатель:** посетитель — что это такое и стоит ли брать.

[![Состояние: Python и его версия, ОС linux / windows / mac, покрытие, выпуск, версия проекта](https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/.github/badges/python.svg)](.github/workflows/ci.yml) [![правил каталога держится машиной](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/.github/badges/rules.json&cacheSeconds=300)](.rules/bindings.json) [![кто из семьи взял наше: проекты и шаги вызовом по тегу, правила гейтом нашего происхождения](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/.github/badges/family.json&cacheSeconds=300)](docs/decisions/016-family-completeness-outranks-the-release-number.md)

**Механизмы конвейера: скелет один для всех проектов, наполнение своё.**
Открытие изменения, гейты, очередь и слияние, здоровье общей ветки, выпуск —
одними и теми же файлами с одними и теми же именами шагов. Своё у проекта —
чем шаг наполнен, и объявляется это данными, а не правкой прогона.

> Правила — в каталоге [Engineering-Incidents-Playbook](https://github.com/ArtVsMark/Engineering-Incidents-Playbook).
> Неофициально, к Anthropic отношения не имеет.

## Зачем

Проекты одной семьи держали конвейер копиями, и копии разошлись полностью:
ни одна сверенная пара одноимённых файлов не совпала (замер — в
[`docs/use/pipeline.md`](docs/use/pipeline.md)). Цена расхождения — простои:
обязательная проверка, которой не выдаёт ни один прогон, останавливает слияния
и не краснеет нигде.

## Граница: чем это не является

**Каталог держит правила, этот проект — механизмы**
([«Граница проекта»](docs/use/pipeline.md#граница-проекта)). Это **не сборник
заготовок для копирования**: механизмы берут версией, к которой прибиты.
Заготовки для тех, кому механизмы недоступны, — у каталога, в
[`templates/`](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/tree/main/templates).

## Что можно взять

Проверяющие шаги — джобами вашего `ci.yml`, вызовом по адресу с версией: [`step-lint.yml`](.github/workflows/step-lint.yml) ·
[`step-pr-meta.yml`](.github/workflows/step-pr-meta.yml) ·
[`step-journal.yml`](.github/workflows/step-journal.yml) ·
[`step-attribution.yml`](.github/workflows/step-attribution.yml) ·
[`step-pipeline.yml`](.github/workflows/step-pipeline.yml) ·
[`step-contract.yml`](.github/workflows/step-contract.yml) ·
[`step-debt.yml`](.github/workflows/step-debt.yml) ·
[`step-window-lifetime.yml`](.github/workflows/step-window-lifetime.yml) ·
[`step-rulebook-fresh.yml`](.github/workflows/step-rulebook-fresh.yml)

Управляющие — тем же вызовом, но своим прогоном со своими событиями: [`step-work-plan.yml`](.github/workflows/step-work-plan.yml)
(план работ) · [`step-automerge.yml`](.github/workflows/step-automerge.yml)
(очередь и слияние) · [`step-main-red.yml`](.github/workflows/step-main-red.yml)
(дежурный по общей ветке) · [`step-stuck.yml`](.github/workflows/step-stuck.yml)
(застрявшее) · [`step-hail.yml`](.github/workflows/step-hail.yml) (оклик) ·
[`step-verify-queue.yml`](.github/workflows/step-verify-queue.yml) (верификатор по плану) ·
[`step-drift.yml`](.github/workflows/step-drift.yml) (дрейф внешних входов) ·
[`step-review.yml`](.github/workflows/step-review.yml) (внешний взгляд и реестр находок) ·
[`step-facts.yml`](.github/workflows/step-facts.yml) (факты о проекте для витрины семьи) ·
[`step-agent-pr.yml`](.github/workflows/step-agent-pr.yml) (открытие изменения) ·
[`step-task-items.yml`](.github/workflows/step-task-items.yml) (разбор слитого против задачи).
Токен владельца `MERGE_QUEUE_TOKEN` и ключ агента `CLAUDE_CODE_OAUTH_TOKEN`
передаются вызовом явно, по имени: секретов вызывающего общий шаг не видит.

**Заготовку вызова печатает `scripts/onboard.py`**: джобы с прибивкой к
последнему выпуску, ответ по каждой проверке и данные, которые заводите вы.
Кто подключён и что у него обойдено, печатает `scripts/consumers.py`.
**Как подключиться и куда идти, если что-то пошло не так, —
[`docs/use/onboarding.md`](docs/use/onboarding.md).**

**Чего ещё нет** — названо, потому что отсутствующий механизм снаружи
неотличим от молчащего
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)):
прогона переноса целиком в чужом дереве ([#1191](../../issues/1191)) и
оповещения потребителей при смене версии контракта — подключённых, кроме нас
самих, пока нет. Всё недоказанное прогоном — в [`docs/dev/gaps.md`](docs/dev/gaps.md).

**Значки в шапке собраны прогоном, а не вписаны руками**: `badges.yml` после
каждого слияния пересчитывает их и факты о проекте (`facts.json`) в отдельную
ветку `badges`
([160](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/160-derived-artifacts-live-off-the-branch.md)).
Первый значок общий для семьи: версии Python и ОС окрашены исходом своих
прогонов, серое — не проверялось. Факты по тому же адресу читают соседи и
каталог правил
([174](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/174-facts-about-a-project-are-published-by-it.md)).

## Что читать

| Документ | Отвечает на вопрос |
|---|---|
| [`docs/use/pipeline.md`](docs/use/pipeline.md) | **из чего** конвейер состоит: шаги, файлы, правила формы |
| [`docs/agent/behaviour.md`](docs/agent/behaviour.md) | **что происходит, когда**: три контура, заморозка, предел попыток |
| [`docs/dev/roadmap.md`](docs/dev/roadmap.md) | **в каком порядке** это строится и по чему видно готовность |
| [`AGENTS.md`](AGENTS.md) | что проект требует от агента — ядро |
| [`CLAUDE.md`](CLAUDE.md) | чем агентское окно отличается от любого другого агента |
| [`docs/README.md`](docs/README.md) | **кому что читать**: все документы по читателю |

Документы разделены по читателю, а не по темам
([021](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/021-split-docs-by-reader.md)).

## Как это развивается

Проект — **свой первый потребитель**: механизм, которым не пользуется автор,
находит дыры на чужом проекте в худший момент
([155](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/155-a-template-you-dont-use-drifts.md)).
Наружу механизмы выносятся по проекту семьи за раз — эпик
[#782](../../issues/782); порядок и признаки готовности — в
[`docs/dev/roadmap.md`](docs/dev/roadmap.md). Правило, родившееся здесь,
уезжает в каталог вместе со своим инцидентом
([080](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/080-every-new-rule-goes-into-the-catalogue.md)).

## Второй исход

Перенос может и не окупиться, и этот исход записан заранее: условие остановки —
в [плане развития](docs/dev/roadmap.md#второй-исход).
