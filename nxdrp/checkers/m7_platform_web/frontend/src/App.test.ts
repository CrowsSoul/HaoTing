import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import App from './App.vue'

const book={name:'dfm_default',version:'0.1',schema_version:'1.0.0',updated_at:'',rules:[
  {rule_id:'R-DFM-02',check_item_id:'DFM-02',name:'最小间隙',enabled:true,severity:'P2',params:{min_clearance_mm:.3},notes:'间隙检查'},
  {rule_id:'R-DFM-31',check_item_id:'DFM-31',name:'标准刀具',enabled:true,severity:'P2',params:{standard_diameters:[1,2,3]},notes:'刀具检查'}
]}
const task={id:'a'.repeat(32),model_id:'b'.repeat(32),filename:'board_a.model.json',rulebook_id:'c'.repeat(32),created_at:'2026-10-22T02:00:00Z',only:[],state:'completed',stage:'检查结束',elapsed_ms:20,total_items:2,completed_items:2,summary:{findings:1},queue_position:0}
let wrapper: VueWrapper
let created=false
let saved: typeof book | null=null
const calls:{url:string,options?:RequestInit}[]=[]
beforeEach(()=>{
  created=false; saved=null; calls.length=0
  vi.stubGlobal('fetch',vi.fn(async (url:string,options?:RequestInit)=>{
    calls.push({url,options})
    let data:unknown={}
    if(url==='/api/rulebooks'&&options?.method==='POST') {saved=JSON.parse(options.body as string);data={id:'d'.repeat(32),book:saved,created_at:''}}
    else if(url==='/api/rulebooks') data=[{id:'c'.repeat(32),book,created_at:''}]
    else if(url==='/api/samples') data=['board_a.model.json']
    else if(url==='/api/catalog') data={rows:book.rules.map(r=>({...r,name_cn:r.name,implemented:true,owner_module:'M4'}))}
    else if(url==='/api/health') data={nx_available:false,workers:4,nx_slots:1,m8_available:false}
    else if(url.startsWith('/api/samples/')) data={id:'b'.repeat(32)}
    else if(url==='/api/tasks'&&options?.method==='POST') {created=true;data=task}
    else if(url==='/api/tasks') data=created?[task]:[]
    else if(url.endsWith('/mesh')) return {ok:false,status:404,json:async()=>({detail:'no mesh'})}
    else if(url.endsWith('/model')) data={model_id:'board_a',units:'mm',parts:[],faces:[]}
    else if(url.endsWith('/result')) data={findings:[{finding_id:'F1',check_item_id:'DFM-02',check_item_name:'最小间隙',severity:'P3',message:'间隙不足',measured_value:.15,threshold_value:.3,deviation:-.15,unit:'mm',confidence:.55,location:null,bbox:null,path_points:[],part_refs:['P01'],evidence:{face_ids:['F01'],note:'粗筛'},suggestion:{text:'加大间隙到 0.3 mm'}}],results:[{check_item_id:'DFM-02',name:'最小间隙',status:'ok',finding_count:1,reason:''}],load_errors:[]}
    return {ok:true,json:async()=>JSON.parse(JSON.stringify(data))}
  }))
})
afterEach(()=>{wrapper?.unmount();vi.unstubAllGlobals()})
const render=async()=>{wrapper=mount(App,{global:{stubs:{Viewer:{template:'<div class="viewer-stub">3D 区域</div>'}}}});await flushPromises()}
describe('M7 workflows',()=>{
  it('initializes without cloning reactive proxy errors and edits numeric/list parameters',async()=>{
    await render()
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
    await wrapper.findAll('nav button')[1].trigger('click')
    expect(wrapper.findAll('.rule-card')).toHaveLength(2)
    const numeric=wrapper.find('.rule-card input[type=number]')
    await numeric.setValue('0')
    const add=wrapper.find('.array-editor .quiet'); await add.trigger('click')
    expect(wrapper.findAll('.array-editor input')).toHaveLength(4)
    await wrapper.find('form').trigger('submit');await flushPromises()
    expect(saved!.rules[0].params.min_clearance_mm).toBe(0)
    expect(saved!.rules[1].params.standard_diameters).toHaveLength(4)
    expect(wrapper.find('[role=status]').text()).toContain('已保存新规则版本')
  })
  it('submits an actual task request and renders returned findings and report links',async()=>{
    await render()
    await wrapper.find('form').trigger('submit');await flushPromises()
    const request=calls.find(c=>c.url==='/api/tasks'&&c.options?.method==='POST')!
    expect(JSON.parse(request.options!.body as string)).toEqual({model_id:'b'.repeat(32),rulebook_id:'c'.repeat(32),only:[]})
    expect(wrapper.findAll('.finding-card')).toHaveLength(1)
    expect(wrapper.find('.finding-detail').text()).toContain('加大间隙到 0.3 mm')
    expect(wrapper.find('.finding-detail').text()).toContain('F01')
    expect(wrapper.find(`a[href="/api/tasks/${task.id}/reports/html"]`).exists()).toBe(true)
    expect(wrapper.find('.viewer-stub').exists()).toBe(true)
  })
})
