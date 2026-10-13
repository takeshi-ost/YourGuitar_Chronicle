"""Bounded display bundles; authentication and write authority remain canonical."""
from concurrent.futures import ThreadPoolExecutor

class CloudProfileBundle:
    def __init__(self, users, favorites):
        self.users, self.favorites = users, favorites

    def own_bootstrap(self, actor):
        tasks={'settings':lambda:self.users.own_settings(actor),'inventory':lambda:self.users.own_inventory(actor),
               'favorites':lambda:self.favorites.list(actor,limit=50)}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures={key:pool.submit(fn) for key,fn in tasks.items()}
            result={key:future.result() for key,future in futures.items()}
        inventory=result.pop('inventory');result.update(inventory)
        for kind in ('owned','formerly_owned'):
            p=result[kind]
            result[kind]=dict(items=[{**r,'id':str(r['id'])} for r in p['items']],total=str(p['total']),next_after=str(p['next_after']) if p['next_after'] is not None else None)
        # Revalidate admission/role after independent reads, before disclosure.
        with self.users.operations.account_access('user_read',actor):
            return result
