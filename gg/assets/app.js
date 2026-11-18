(function(){
  var app=document.getElementById('app'); if(!app) return;
  var slug=app.dataset.slug, rel=app.dataset.rel||'';
  var MK=['cdc.gov','epa.gov','usaid.gov','sealevel.globalchange.gov','globalchange.gov','climate.gov','fema.gov','ed.gov','imls.gov','covid.gov','coralreef.gov'];
  var CODE={'404':'404 Not Found','410':'410 Gone','dns':'Website no longer exists','refused':'Server refuses connections','soft':'Shows a “not found” page'};
  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
  function day(t){if(!t||t.length<8)return'';var d=new Date(Date.UTC(+t.slice(0,4),+t.slice(4,6)-1,+t.slice(6,8)));return d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'})}
  function mirror(host,path){var h=host.replace(/^www\./,'').split(':')[0];if(!/\.gov$/.test(h))return'';
    if(!MK.some(function(k){return h===k||h.slice(-k.length-1)==='.'+k}))return'';return 'https://'+h.slice(0,-4).replace(/\./g,'-')+'.govarchive.us'+path}
  var D,rows=[],shown=0,list,cnt,more;
  function qs(){var p=new URLSearchParams(location.hash.slice(1));return p}
  fetch(rel+'data/'+slug+'.json').then(function(r){return r.json()}).then(function(d){D=d;init()}).catch(function(){app.innerHTML='<p>Could not load the list.</p>'});
  function init(){
    var hs=D.hosts.map(function(h,i){return [h,i]}).sort(function(a,b){return a[0]<b[0]?-1:1});
    app.innerHTML='<form class="controls" onsubmit="return false" aria-label="Filter the list">'+
      '<label class="q"><span class="vh">Search</span><input type="search" id="q" placeholder="Search titles and addresses"></label>'+
      '<label><span class="vh">Status</span><select id="st"><option value="">Gone or redirected</option><option value="0">Gone</option><option value="1">Redirected away</option></select></label>'+
      '<label><span class="vh">Type</span><select id="ki"><option value="">Pages and documents</option><option value="0">Web pages</option><option value="1">Documents</option></select></label>'+
      '<label><span class="vh">Wayback Machine</span><select id="wb"><option value="">Any archive</option><option value="1">Has a Wayback copy</option><option value="0">Only in Webrecorder</option></select></label>'+
      '<label><span class="vh">Website</span><select id="ho"><option value="">All websites</option>'+hs.map(function(h){return '<option value="'+h[1]+'">'+esc(h[0])+'</option>'}).join('')+'</select></label>'+
      '<label><span class="vh">Sort</span><select id="so"><option value="a">Address</option><option value="r">Most recently removed</option><option value="t">Title</option></select></label>'+
      '</form><p class="count" id="cnt" aria-live="polite"></p><ol class="rows" id="list"></ol><p><button class="more" id="more" type="button">Show more</button></p>';
    list=document.getElementById('list');cnt=document.getElementById('cnt');more=document.getElementById('more');
    var p=qs();['q','st','ki','wb','ho','so'].forEach(function(k){var el=document.getElementById(k);if(p.get(k))el.value=p.get(k);el.addEventListener(k==='q'?'input':'change',apply)});
    more.addEventListener('click',function(){render(100)});
    apply();
  }
  function apply(){
    var q=document.getElementById('q').value.toLowerCase().trim(),st=document.getElementById('st').value,ki=document.getElementById('ki').value,
        wb=document.getElementById('wb').value,ho=document.getElementById('ho').value,so=document.getElementById('so').value;
    var h=new URLSearchParams();[['q',q],['st',st],['ki',ki],['wb',wb],['ho',ho],['so',so==='a'?'':so]].forEach(function(x){if(x[1])h.set(x[0],x[1])});
    history.replaceState(null,'',h.toString()?'#'+h.toString():location.pathname);
    rows=D.rows.filter(function(r){
      if(st!==''&&String(r[4])!==st)return false; if(ki!==''&&String(r[3])!==ki)return false; if(ho!==''&&String(r[0])!==ho)return false;
      if(wb==='1'&&!r[7])return false; if(wb==='0'&&(r[7]||!r[12]))return false;
      if(q&&(r[1]+' '+r[2]+' '+D.hosts[r[0]]).toLowerCase().indexOf(q)<0)return false; return true});
    if(so==='r')rows.sort(function(a,b){return (b[8]||b[7]||'')<(a[8]||a[7]||'')?-1:1});
    else if(so==='t')rows.sort(function(a,b){return (a[2]||'~').localeCompare(b[2]||'~')});
    else rows.sort(function(a,b){var x=D.hosts[a[0]]+a[1],y=D.hosts[b[0]]+b[1];return x<y?-1:x>y?1:0});
    list.innerHTML='';shown=0;render(100);
  }
  function render(k){
    var html='';
    for(var i=shown;i<Math.min(rows.length,shown+k);i++){var r=rows[i],host=D.hosts[r[0]],u='https://'+host+r[1];
      var name=r[2]||decodeURIComponent((r[1].split('?')[0].replace(/\/$/,'').split('/').pop())||host).replace(/[-_]+/g,' ')||r[1];
      var wbl=r[7]?'https://web.archive.org/web/'+r[7]+'/'+(r[10]||u):'';
      var mir=mirror(host,r[1]);
      var stx=r[4]?'Redirects to <a href="'+esc(r[6])+'" rel="nofollow">'+esc(r[6].replace(/^https?:\/\//,'').slice(0,90))+'</a>':esc(CODE[r[5]]||('HTTP '+r[5]));
      var wtx=r[7]?'<span>Last working copy: <a href="'+esc(wbl)+'">'+day(r[7])+'</a>'+(r[8]?', missing by '+day(r[8]):'')+'</span>':(r[12]?'<span class="muted">No working copy in the Wayback Machine</span>':'<span class="muted">Wayback lookup pending</span>');
      html+='<li><div class="t"><span class="badge '+(r[4]?'away">Redirected':'gone">Gone')+'</span>'+(r[3]?'<span class="badge doc">Document</span>':'')+
        (wbl?'<a href="'+esc(wbl)+'">'+esc(name)+'</a>':(mir?'<a href="'+esc(mir)+'">'+esc(name)+'</a>':esc(name)))+'</div>'+
        '<div class="u">'+esc(host+r[1])+'</div><div class="m"><span>'+stx+'</span>'+wtx+
        (mir?'<span><a href="'+esc(mir)+'">Webrecorder copy</a>'+(r[11]?' ('+day(r[11])+')':'')+'</span>':'')+
        '<span><a href="'+esc(u)+'" rel="nofollow">Live address</a></span></div></li>'}
    list.insertAdjacentHTML('beforeend',html);shown=Math.min(rows.length,shown+k);
    cnt.textContent=rows.length.toLocaleString('en-US')+' addresses'+(rows.length>shown?' · showing '+shown.toLocaleString('en-US'):'');
    more.hidden=shown>=rows.length;
  }
})();
