# Engineering Pipeline Mechanisms

> **Читатель:** посетитель — что это такое и стоит ли брать.

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
[`docs/pipeline.md`](docs/pipeline.md); он с датой, и второй раз здесь не
приводится, чтобы не разойтись с первым
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

Расхождение стоит не аккуратности, а простоев: обязательная проверка, которой
не выдаёт ни один прогон, останавливает слияния целиком — и не краснеет нигде,
потому что краснеть нечему.

## Граница: чем это не является

**Каталог держит правила. Этот проект держит механизмы.** Файл живёт здесь,
если реализует правило каталога, общее для нескольких проектов. Про предмет
одного проекта — остаётся дома. Мерка не «похоже», а «реализует общее правило».

Это **не сборник заготовок для копирования**: подключение к общим механизмам
идёт версией, к которой потребитель прибит, а не переносом файлов руками.
Заготовки для того, кому механизмы недоступны, лежат у каталога — в
[`templates/`](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/tree/main/templates).

## Что можно взять: девять шагов конвейера

Шаг берётся **вызовом по адресу с версией**, а не копией файла к себе. Копия —
ровно та беда, из-за которой передача и затевалась: замер 09.09.2026 по пяти
проектам нашёл десять повторяющихся имён прогонов, и **ни одна пара копий не
совпала**.

```yaml
jobs:
  lint:
    name: lint
    uses: ArtVsMark/Engineering-Pipeline-Mechanisms/.github/workflows/step-lint.yml@v1.1.0
```

| шаг | что делает |
|---|---|
| [`step-lint.yml`](.github/workflows/step-lint.yml) | линтер, формат и типы одним джобом |
| [`step-pr-meta.yml`](.github/workflows/step-pr-meta.yml) | метки изменения и связь с задачей |
| [`step-journal.yml`](.github/workflows/step-journal.yml) | фрагмент журнала, версия, разбор фрагментов |
| [`step-attribution.yml`](.github/workflows/step-attribution.yml) | автор коммитов — человек, агент соавтор |
| [`step-pipeline.yml`](.github/workflows/step-pipeline.yml) | ответ по классам проверок полон и сходится с деревом |
| [`step-contract.yml`](.github/workflows/step-contract.yml) | поверхность контракта не тронута молча |
| [`step-debt.yml`](.github/workflows/step-debt.yml) | остаток долга виден на каждом изменении |
| [`step-window-lifetime.yml`](.github/workflows/step-window-lifetime.yml) | срок жизни окна, открывшего изменение |
| [`step-rulebook-fresh.yml`](.github/workflows/step-rulebook-fresh.yml) | свод не менялся под окном изменения |

**Имя записи проверки у вызванного шага СОСТАВНОЕ** — `<имя вашего джоба> / <имя
шага>`. В примере выше запись придёт именем `lint / lint`, и именно его называют
в своём `.pipeline.yml` и в защите ветки. Это замер прогоном на живой площадке,
а не чтение документации
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

**Чего ещё нет, и это названо, а не умолчано:** команды подключения одним
заходом, канала обратной связи от потребителей, потребительской половины
контракта связи. Семейство `test` (матрица версий и агрегат) и сводный гейт
`ci-complete` не вынесены намеренно: имена первых несут ячейку матрицы, а второй
— единственный обязательный контекст защиты, живущей вне дерева. Порядок работ —
эпик [#547](../../issues/547).

Названо это здесь потому, что отсутствующий механизм и молчащий механизм
снаружи неотличимы
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
Что именно ещё не доказано прогоном — таблицей в [`AGENTS.md`](AGENTS.md).

Значки ниже собраны прогоном, а не вписаны руками: `badges.yml` пересчитывает
`facts.json` и весь набор значков на каждое слияние и толкает их в отдельную
ветку `badges` — производное не коммитится туда, где живёт источник, и не
конфликтует на каждом слиянии
([160](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/160-derived-artifacts-live-off-the-branch.md)).
Строка о нём ушла из таблицы пробелов после первого прогона публикации, а не
после написания кода
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

![правил каталога держится машиной](https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/rules.svg) ![доля машинного соблюдения семьи, закрытая общими механизмами](https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/family.svg) ![версия проекта, посчитанная по истории](https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/version.svg) ![последний выпуск: к нему прибивается потребитель](https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/release.svg) ![запускаемых механизмов гоняется процессом](https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/scripts.svg) ![доля покрытых строк: мерило охвата, а не верности механизма](https://raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/badges/coverage.svg)

Тем же файлом открыт канал соседям и каталогу правил: версия контракта,
сколько правил каталога проект держит и чем именно, состав классов проверок —
всё читается по адресу raw ветки `badges`, без клона дерева. Факты о проекте
публикует сам проект
([174](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/174-facts-about-a-project-are-published-by-it.md)).

Порядок подключения потребителей и признаки готовности каждого этапа —
[`docs/roadmap.md`](docs/roadmap.md).

## Что читать

| Документ | Отвечает на вопрос |
|---|---|
| [`docs/pipeline.md`](docs/pipeline.md) | **из чего** конвейер состоит: шаги, файлы, правила формы |
| [`docs/behaviour.md`](docs/behaviour.md) | **что происходит, когда**: три контура, заморозка, предел попыток |
| [`docs/roadmap.md`](docs/roadmap.md) | **в каком порядке** это строится и по чему видно готовность |
| [`AGENTS.md`](AGENTS.md) | что проект требует от агента — ядро |
| [`CLAUDE.md`](CLAUDE.md) | чем агентское окно отличается от любого другого агента |

Разделение не по темам, а по читателю: одному нужен состав, другому поведение,
и второе из первого не выводится
([021](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/021-split-docs-by-reader.md)).

## Как это развивается

Проект — **свой первый потребитель**. Механизм, которым не пользуется его
автор, находит свои дыры на чужом проекте и в худший момент
([155](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/155-a-template-you-dont-use-drifts.md)).
Поэтому собственная обвязка идёт раньше выноса общих механизмов наружу, и
11.09.2026 это стало **порядком работ, а не пожеланием**: вынос отложен целиком
до того дня, когда конвейер закроет собственные вопросы проекта
([#196](../../issues/196)).

Правило, родившееся здесь, уезжает в каталог вместе со своим инцидентом:
формулировка остаётся тут, разбор живёт там
([080](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/080-every-new-rule-goes-into-the-catalogue.md)).

## Второй исход

Если окажется, что общий модуль не окупается — цена версионирования и гейта на
дрейф выше выигрыша, — работы останавливаются, а вывод записывается отказом с
причиной. Это предусмотрено заранее, чтобы перенос не превратился в поиск
подтверждения.
