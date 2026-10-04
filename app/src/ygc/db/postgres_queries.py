"""Parameter binding for shared Observation queries; no SQL dialect rewriting."""


def qmark_parameters(query):
    """Translate unquoted DB-API markers only, preserving literals and comments."""
    query = query.replace('%', '%%')
    result = []
    quote = None
    i = 0
    while i < len(query):
        char = query[i]
        if quote:
            result.append(char)
            if char == quote:
                if i + 1 < len(query) and query[i + 1] == quote:
                    result.append(query[i + 1])
                    i += 1
                else:
                    quote = None
        elif query.startswith('--', i):
            end = query.find('\n', i)
            end = len(query) if end < 0 else end
            result.append(query[i:end])
            i = end - 1
        elif query.startswith('/*', i):
            end = query.find('*/', i + 2)
            if end < 0:
                raise ValueError('Unclosed SQL comment')
            result.append(query[i:end + 2])
            i = end + 1
        elif char in "'\"":
            quote = char
            result.append(char)
        elif char == '?':
            result.append('%s')
        elif char == '$':
            raise ValueError('Dollar quoting is not supported in shared queries')
        else:
            result.append(char)
        i += 1
    if quote:
        raise ValueError('Unclosed SQL quote')
    return ''.join(result)


class ObservationConnection:
    """Expose portable shared business SQL with PostgreSQL parameter binding."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=None):
        if parameters is None:
            cursor = self.connection.execute(query)
        else:
            cursor = self.connection.execute(qmark_parameters(query), parameters)
        return SharedCursor(cursor)


class SharedRow(dict):
    """Shared algorithms may use column names or positional scalar results."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class SharedCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        row = self.cursor.fetchone()
        return SharedRow(row) if row is not None else None

    def fetchall(self):
        return [SharedRow(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        for row in self.cursor:
            yield SharedRow(row)

    @property
    def rowcount(self):
        return self.cursor.rowcount
