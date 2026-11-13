"""Açık web sayfalarını yeniden alır; erişim puan veya insan onayı değildir."""
import socket,ipaddress,hashlib
from urllib.parse import urlparse
from urllib.request import Request,build_opener,HTTPRedirectHandler,ProxyHandler
from html.parser import HTMLParser
from datetime import datetime,timezone

def public_url(url):
    u=urlparse(url)
    if u.scheme not in {'https','http'} or not u.hostname or u.username or u.password or u.port not in {None,80,443}:
        raise ValueError('Yalnız herkese açık HTTP/HTTPS sayfaları kullanılabilir.')
    addresses=socket.getaddrinfo(u.hostname,u.port or (443 if u.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('Yerel veya özel ağ adresi kullanılamaz.')
    return url

class Redirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','nav','footer'}:self.skip+=1
    def handle_endtag(self,tag):
        if tag in {'script','style','nav','footer'}:self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip and data.strip():self.parts.append(data.strip())

def fetch(url):
    result=dict(url=url,at=datetime.now(timezone.utc).isoformat())
    try:
        public_url(url)
        with build_opener(ProxyHandler({}),Redirects()).open(Request(url,headers={'User-Agent':'CallMetric-Research-Prototype/1.0'}),timeout=12) as response:
            if 'text/html' not in response.headers.get('Content-Type',''):raise ValueError('Bu kontrol yalnız HTML web sayfalarını destekler.')
            raw=response.read(1_000_001)
            if len(raw)>1_000_000:raise ValueError('Sayfa 1 MB sınırını aşıyor.')
            parser=Text();parser.feed(raw.decode(response.headers.get_content_charset() or 'utf-8',errors='replace'))
            text=' '.join(parser.parts)
            if len(text)<100:raise ValueError('Yeterli metin alınamadı; sayfa elle açılarak incelenmeli.')
            result.update(text=text,hash=hashlib.sha256(text.encode()).hexdigest(),final_url=response.url,error='')
    except Exception as exc:result['error']=str(exc)
    return result
