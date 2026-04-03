"""Static texts used by the Telegram bot."""

USER_ENTRY_BANNER = "!!!ПОЛЬЗОВАТЕЛЬСКИЙ ПЕРЕВОД!!!"

WELCOME_TEXT = (
    "Это словарь кубачинского языка.\n\n"
    "Отправьте слово на русском или кубачинском, и я постараюсь найти перевод.\n"
    "Как пользоваться ботом: /info"
)

ENTER_WORD_TEXT = "Напишите слово или короткую фразу на русском или кубачинском языке."
HELP_TEXT = (
    "Что можно сделать:\n"
    "- найти перевод слова или фразы\n"
    "- переключить режим поиска: /mode\n"
    "- предложить новый перевод: /add\n"
    "- оставить комментарий к статье: /comment\n"
    "- отправить идею или замечание: /suggest"
)
COMMENT_HINT_TEXT = (
    "Если хотите добавить уточнение, синоним или свой вариант перевода, "
    "ответьте на нужную словарную статью командой /comment."
)
SUGGEST_PROMPT_TEXT = (
    "Напишите одним сообщением идею, пожелание или описание проблемы. Я передам это администратору."
)
SUGGEST_SUCCESS_TEXT = "Спасибо. Ваше предложение отправлено."
SUGGEST_EMPTY_TEXT = "Нужно прислать текст одним сообщением."
SUGGEST_UNAVAILABLE_TEXT = "Сейчас предложения временно недоступны. Попробуйте позже."
NO_MORE_RESULTS_TEXT = "Больше результатов нет. Можете ввести другое слово."
PAGINATION_TEXT = "Показать ещё 10 результатов?"
SEARCH_TOO_MANY_TEXT = (
    "Нашлось слишком много вариантов. Попробуйте уточнить запрос: "
    "добавить ещё одно слово или написать фразу точнее."
)
SEARCH_NOT_FOUND_LITE_TEXT = (
    "Пока ничего не нашлось.\n\n"
    "Попробуйте:\n"
    "- проверить написание\n"
    "- открыть /mode и включить расширенный поиск\n"
    "- отправить не одно слово, а короткую фразу\n"
    "- если вы знаете перевод, добавить его через /add"
)
SEARCH_NOT_FOUND_COMPLEX_TEXT = (
    "Пока ничего не нашлось.\n\n"
    "Попробуйте переформулировать запрос или написать другое слово. "
    "Если вы знаете перевод, его можно добавить через /add."
)
MODE_PROMPT_TEXT = (
    "Выберите режим поиска:\n\n"
    "Точный поиск: лучше для одного слова.\n"
    "Расширенный поиск: лучше для фраз, описаний и неточных запросов."
)
MODE_LITE_TEXT = "Включен точный поиск. Он лучше подходит для отдельных слов."
MODE_COMPLEX_TEXT = "Включен расширенный поиск. Он лучше подходит для фраз и описаний."
MODE_ERROR_TEXT = "Не удалось изменить режим поиска. Попробуйте ещё раз."
MODE_LITE_BUTTON_TEXT = "Точный"
MODE_COMPLEX_BUTTON_TEXT = "Расширенный"
ADMIN_ONLY_TEXT = "Команда доступна только администратору."
EXPORT_CAPTION = "Экспорт базы данных"
GENERIC_ERROR_TEXT = "Что-то пошло не так. Попробуйте ещё раз немного позже."

INFO_TEXT = """Этот бот помогает искать переводы слов и выражений
между кубачинским и русским языками.

Как пользоваться:
1. Просто отправьте слово или короткую фразу.
2. Если ничего не нашлось, попробуйте /mode и включите расширенный поиск.
3. Если знаете перевод, которого нет в словаре, добавьте его через /add.
4. Если хотите уточнить словарную статью, ответьте на неё командой /comment.
5. Если есть идея или замечание, используйте /suggest.

Про режимы поиска:
- Точный поиск лучше подходит для одного слова.
- Расширенный поиск лучше подходит для фраз, описаний и неточных запросов.

Если для ввода нужна вертикальная черта, можно использовать один из символов:
1  !  i  I  l  L  |

Словарная база:
Кубачинско-русский словарь: Магомедов Амирбек Джалилович,
Саидов-Аккутта Набигулла Ибрагимович. Москва: Наука, 2017 г.

Идея: Шамов Салам Меджидович
Разработчик: Умаров Арсен Рамазанович"""

ADD_GUIDE_TEXT = """Сейчас я помогу добавить новый перевод. Нужны 4 шага:

1. Слово на кубачинском. Если есть синонимы, перечислите через запятую.
2. Перевод.
3. Примеры или фразы с переводом. Если их несколько, разделяйте знаком %.
4. Дополнительная информация. Если записей несколько, разделяйте знаком \\.

Если какого-то пункта нет, можно отправить 0."""

ADD_WORD_PROMPT = "Шаг 1 из 4. Напишите слово на кубачинском."
ADD_TRANSLATION_PROMPT = "Шаг 2 из 4. Напишите перевод на русском."
ADD_PHRASES_PROMPT = (
    "Шаг 3 из 4. Напишите примеры или фразы. Если их несколько, разделяйте знаком %."
)
ADD_SUPPORTING_PROMPT = "Шаг 4 из 4. Напишите дополнительную информацию. Если её нет, отправьте 0."
ADD_CONFIRM_PROMPT = 'Добавить эту словарную статью? Ответьте "Да" или "Нет".'
ADD_SUCCESS_TEXT = "Спасибо. Запись добавлена."
ADD_CANCELLED_TEXT = "Добавление отменено."
ADD_INVALID_CONFIRM_TEXT = 'Пожалуйста, ответьте только "Да" или "Нет".'
ADD_STATE_MISSING_TEXT = "Не удалось продолжить добавление. Начните заново через /add."

COMMENT_NEEDS_REPLY_TEXT = (
    "Чтобы добавить комментарий, ответьте командой /comment на нужную словарную статью."
)
COMMENT_PROMPT = "Напишите комментарий к этой словарной статье. Его увидят другие пользователи."
COMMENT_SUCCESS_TEXT = "Спасибо. Комментарий добавлен."
COMMENT_NOT_FOUND_TEXT = (
    "Не удалось определить, к какой статье добавить комментарий. Попробуйте ещё раз."
)
COMMENT_STATE_MISSING_TEXT = "Не удалось продолжить комментарий. Начните заново через /comment."

ADMIN_ROOT_TEXT = """Админ-панель.

Доступные разделы:
- Рассылка
- Пользовательские статьи
- Комментарии
- Предложения
- Статистика"""

ADMIN_CANCELLED_TEXT = "Действие отменено."
ADMIN_STATE_MISSING_TEXT = "Не удалось продолжить сценарий админки. Начните заново через /admin."

ADMIN_BROADCAST_TEXT_PROMPT = (
    "Пришлите сообщение для промо-рассылки одним сообщением. "
    "Можно отправить текст, фото с подписью или файл с подписью. "
    "После этого я покажу превью и дам выбрать аудиторию."
)
ADMIN_BROADCAST_EMPTY_TEXT = "Текст рассылки не должен быть пустым."
ADMIN_BROADCAST_UNSUPPORTED_TEXT = (
    "Поддерживаются текст, фото с подписью или файл с подписью. "
    "Попробуйте отправить рассылку одним сообщением."
)
ADMIN_BROADCAST_PREVIEW_TITLE = "Превью рассылки"
ADMIN_BROADCAST_AUDIENCE_PROMPT = "Выберите аудиторию рассылки:"
ADMIN_BROADCAST_DAYS_PROMPT = (
    "Введите число дней активности. Рассылка уйдет тем, кто писал боту за этот период."
)
ADMIN_BROADCAST_DAYS_ERROR_TEXT = "Нужно ввести положительное число дней."
ADMIN_BROADCAST_CONFIRM_TITLE = "Подтвердите рассылку"
ADMIN_BROADCAST_SENT_TEXT = "Рассылка завершена."
ADMIN_BROADCAST_NO_RECIPIENTS_TEXT = "Для выбранного сегмента нет адресатов."
ADMIN_BROADCAST_REPORT_TEXT = (
    "Отчет по рассылке:\n"
    "Успешно: {success}\n"
    "Заблокировали бота: {blocked}\n"
    "Ошибки доставки: {errors}"
)

ADMIN_ENTRIES_EMPTY_TEXT = "Пользовательские статьи не найдены."
ADMIN_ENTRIES_LIST_TITLE = "Пользовательские статьи"
ADMIN_ENTRIES_WORD_FILTER_PROMPT = "Введите слово или часть перевода для фильтра."
ADMIN_ENTRIES_AUTHOR_FILTER_PROMPT = "Введите username, имя или chat_id автора."
ADMIN_ENTRIES_OPEN_PROMPT = "Введите ID статьи, чтобы открыть полную карточку."
ADMIN_ENTRIES_DELETE_CONFIRM_TEXT = (
    "Удалить пользовательскую статью #{entry_id}? Действие необратимо."
)
ADMIN_ENTRIES_DELETE_SUCCESS_TEXT = "Статья удалена."
ADMIN_ENTRIES_EDIT_SUCCESS_TEXT = "Статья обновлена."
ADMIN_ENTRIES_NOT_FOUND_TEXT = "Статья не найдена."
ADMIN_ENTRY_ID_ERROR_TEXT = "Нужно ввести числовой ID статьи."
ADMIN_ENTRY_EDIT_WORD_PROMPT = "Введите новое слово на кубачинском."
ADMIN_ENTRY_EDIT_TRANSLATION_PROMPT = "Введите новый перевод."
ADMIN_ENTRY_EDIT_PHRASES_PROMPT = (
    "Введите новые фразы с переводами, разделяя записи знаком %. Пустое сообщение очистит поле."
)
ADMIN_ENTRY_EDIT_SUPPORTING_PROMPT = (
    "Введите новую вспомогательную информацию, разделяя записи знаком \\. "
    "Пустое сообщение очистит поле."
)

ADMIN_COMMENTS_EMPTY_TEXT = "Комментарии не найдены."
ADMIN_COMMENTS_LIST_TITLE = "Комментарии"
ADMIN_COMMENTS_ENTRY_FILTER_PROMPT = "Введите слово, перевод или ID статьи для фильтра."
ADMIN_COMMENTS_AUTHOR_FILTER_PROMPT = "Введите username, имя или chat_id автора комментария."
ADMIN_COMMENTS_DELETE_PROMPT = "Введите ID комментария, который нужно удалить."
ADMIN_COMMENTS_DELETE_SUCCESS_TEXT = "Комментарий удален."
ADMIN_COMMENTS_NOT_FOUND_TEXT = "Комментарий не найден."
ADMIN_COMMENT_ID_ERROR_TEXT = "Нужно ввести числовой ID комментария."

ADMIN_SUGGESTIONS_EMPTY_TEXT = "Предложения пока не приходили."
ADMIN_SUGGESTIONS_LIST_TITLE = "Предложения пользователей"

ADMIN_STATS_TOP_QUERIES_EMPTY_TEXT = "Нет данных"
ADMIN_STATS_TITLE = "Статистика бота"

ADMIN_BROADCAST_MENU_TEXT = ADMIN_BROADCAST_AUDIENCE_PROMPT
ADMIN_BROADCAST_TEXT_PROMPT_TEXT = ADMIN_BROADCAST_TEXT_PROMPT
ADMIN_BROADCAST_DAYS_PROMPT_TEXT = ADMIN_BROADCAST_DAYS_PROMPT
ADMIN_BROADCAST_AUDIENCE_ERROR_TEXT = "Нужно выбрать аудиторию рассылки."
ADMIN_BROADCAST_CONFIRM_TEXT = ADMIN_BROADCAST_CONFIRM_TITLE
ADMIN_BROADCAST_REPORT_TITLE_TEXT = "Отчет по рассылке:"

ADMIN_ENTRIES_TITLE_TEXT = ADMIN_ENTRIES_LIST_TITLE
ADMIN_ENTRIES_WORD_FILTER_PROMPT_TEXT = ADMIN_ENTRIES_WORD_FILTER_PROMPT
ADMIN_ENTRIES_AUTHOR_FILTER_PROMPT_TEXT = ADMIN_ENTRIES_AUTHOR_FILTER_PROMPT
ADMIN_ENTRIES_OPEN_PROMPT_TEXT = ADMIN_ENTRIES_OPEN_PROMPT
ADMIN_ENTRY_EDIT_WORD_PROMPT_TEXT = ADMIN_ENTRY_EDIT_WORD_PROMPT
ADMIN_ENTRY_EDIT_TRANSLATION_PROMPT_TEXT = ADMIN_ENTRY_EDIT_TRANSLATION_PROMPT
ADMIN_ENTRY_EDIT_PHRASES_PROMPT_TEXT = ADMIN_ENTRY_EDIT_PHRASES_PROMPT
ADMIN_ENTRY_EDIT_SUPPORTING_PROMPT_TEXT = ADMIN_ENTRY_EDIT_SUPPORTING_PROMPT
ADMIN_ENTRY_EDIT_EMPTY_TEXT = "Нужно прислать новый текст одним сообщением."
ADMIN_ENTRY_DETAIL_TITLE_TEXT = "Полная карточка статьи"

ADMIN_COMMENTS_TITLE_TEXT = ADMIN_COMMENTS_LIST_TITLE
ADMIN_COMMENTS_ENTRY_FILTER_PROMPT_TEXT = ADMIN_COMMENTS_ENTRY_FILTER_PROMPT
ADMIN_COMMENTS_AUTHOR_FILTER_PROMPT_TEXT = ADMIN_COMMENTS_AUTHOR_FILTER_PROMPT
ADMIN_COMMENT_DETAIL_TITLE_TEXT = "Полная карточка комментария"

ADMIN_SUGGESTIONS_TITLE_TEXT = ADMIN_SUGGESTIONS_LIST_TITLE
ADMIN_SUGGESTION_DETAIL_TITLE_TEXT = "Полная карточка предложения"

ADMIN_STATS_TITLE_TEXT = ADMIN_STATS_TITLE
