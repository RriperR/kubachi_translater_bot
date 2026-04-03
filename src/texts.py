"""Static texts used by the Telegram bot."""

USER_ENTRY_BANNER = "!!!ПОЛЬЗОВАТЕЛЬСКИЙ ПЕРЕВОД!!!"

WELCOME_TEXT = "Бот-словарь кубачинского языка.\n\nДополнительная информация: /info"

ENTER_WORD_TEXT = "Введите слово на русском или кубачинском языке:"
HELP_TEXT = "Предложить идею или улучшение бота: /suggest"
COMMENT_HINT_TEXT = (
    "Вы можете добавить свою версию перевода, синоним или комментарий, "
    "ответив на нужное сообщение командой /comment."
)
SUGGEST_PROMPT_TEXT = (
    "Опишите идею, улучшение или проблему одним сообщением. Я передам это администратору."
)
SUGGEST_SUCCESS_TEXT = "Спасибо. Ваше предложение отправлено."
SUGGEST_EMPTY_TEXT = "Нужно прислать текст предложения одним сообщением."
SUGGEST_UNAVAILABLE_TEXT = "Предложка сейчас недоступна. Попробуйте позже или напишите через /help."
NO_MORE_RESULTS_TEXT = "Больше результатов нет. Можете ввести другое слово."
PAGINATION_TEXT = "Выведено 10 словарных статей, вывести ещё 10?"
SEARCH_TOO_MANY_TEXT = "Результатов поиска более 100, измените запрос. /help"
SEARCH_NOT_FOUND_LITE_TEXT = (
    "Такое слово не найдено. Попробуйте поменять режим поиска на "
    '"комплексный" через /mode. Если вы знаете перевод, можете добавить '
    "его с помощью команды /add."
)
SEARCH_NOT_FOUND_COMPLEX_TEXT = (
    "Такое слово не найдено. Если вы знаете перевод, можете добавить его с помощью команды /add."
)
MODE_PROMPT_TEXT = "Выберите режим перевода:"
MODE_LITE_TEXT = "Выбран простой режим перевода."
MODE_COMPLEX_TEXT = "Выбран комплексный режим перевода."
MODE_ERROR_TEXT = "Не удалось обновить режим поиска. /help"
ADMIN_ONLY_TEXT = "Команда доступна только администратору."
EXPORT_CAPTION = "Экспорт базы данных"
GENERIC_ERROR_TEXT = "Произошла ошибка. Если проблема повторится, опишите её через /suggest."

INFO_TEXT = """Кубачинско-русский словарь, бот-переводчик, с примерами.
Реализация: Умаров Арсен Рамазанович
Идея: Шамов Салам Меджидович
Словарная база:
Кубачинско-русский словарь: Магомедов Амирбек Джалилович,
Саидов-Аккутта Набигулла Ибрагимович. Москва: Наука, 2017 г.

Для диграмм, где вертикальная черта вводится вручную, можно использовать символы:
1  !  i  I  l  L  |

Для изменения режима перевода используйте /mode.
Простой режим ищет слово целиком.
Комплексный режим ищет совпадения в том числе внутри фраз.
Чтобы добавить свой перевод, используйте /add, затем следуйте инструкциям.
Чтобы предложить идею или улучшение бота, используйте /suggest.
По дополнительным вопросам: @RipeR3d"""

ADD_GUIDE_TEXT = """Для добавления словарной статьи введите по очереди:

1. Слово на кубачинском. Если есть синонимы, перечислите через запятую.
2. Перевод.
3. Фразы с переводом, разделяя их знаком %.
4. Вспомогательную информацию, разделяя её знаком \\.

По дополнительным вопросам: /help"""

ADD_WORD_PROMPT = "Введите слово на кубачинском:"
ADD_TRANSLATION_PROMPT = "Введите перевод:"
ADD_PHRASES_PROMPT = "Введите фразы с переводами, отделяя знаком %:"
ADD_SUPPORTING_PROMPT = "Введите вспомогательную информацию (0, если её нет):"
ADD_CONFIRM_PROMPT = 'Добавить словарную статью? Ответьте "Да" или "Нет".'
ADD_SUCCESS_TEXT = "Запись успешно добавлена."
ADD_CANCELLED_TEXT = "Запись отменена. Возникли проблемы? /help"
ADD_INVALID_CONFIRM_TEXT = 'Некорректный ввод. Ответьте "Да" или "Нет".'
ADD_STATE_MISSING_TEXT = "Не удалось продолжить добавление. Начните заново командой /add."

COMMENT_NEEDS_REPLY_TEXT = "Нужно ответить на сообщение, к которому вы хотите добавить комментарий."
COMMENT_PROMPT = "Введите свой комментарий к словарной статье. Он будет виден всем пользователям:"
COMMENT_SUCCESS_TEXT = "Комментарий успешно добавлен."
COMMENT_NOT_FOUND_TEXT = "Не удалось найти словарную статью для комментария. /help"
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
