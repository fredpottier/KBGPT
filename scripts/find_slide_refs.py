from qdrant_client import QdrantClient
from knowbase.config.settings import get_settings

settings = get_settings()
client = QdrantClient(host='qdrant', port=6333)
collection = settings.qdrant_collection
patterns = ['slide ', 'slides ']
matching = []
offset = None
while True:
    points, offset = client.scroll(
        collection_name=collection,
        limit=256,
        with_payload=True,
        offset=offset,
    )
    if not points:
        break
    for pt in points:
        payload = pt.payload or {}
        text = payload.get('text')
        if not isinstance(text, str):
            continue
        lower = text.lower()
        if any(p in lower for p in patterns):
            matching.append({
                'id': pt.id,
                'text': text,
                'source': payload.get('document', {}).get('source_name'),
                'slide_index': payload.get('chunk', {}).get('slide_index'),
            })
            if len(matching) >= 20:
                break
    if len(matching) >= 20 or offset is None:
        break

for idx, item in enumerate(matching, 1):
    snippet = item['text'].replace('\n', ' ')
    if len(snippet) > 400:
        snippet = snippet[:400] + '...'
    print(f"#{idx} id={item['id']} slide={item['slide_index']} source={item['source']}")
    print(snippet)
    print('-' * 80)

print(f"Total matches collected: {len(matching)}")
