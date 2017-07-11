var ui=null,view=null,browser_router=null;require(["utils/utils","libs/jquery/jquery.event.drag","libs/jquery/jquery.event.hover","libs/jquery/jquery.mousewheel","libs/jquery/jquery-ui","libs/jquery/select2","libs/farbtastic","libs/jquery/jquery.form","libs/jquery/jquery.rating","ui/editable-text"],function(a){a.cssLoadFile("static/style/jquery.rating.css"),a.cssLoadFile("static/style/autocomplete_tagging.css"),a.cssLoadFile("static/style/jquery-ui/smoothness/jquery-ui.css"),a.cssLoadFile("static/style/library.css"),a.cssLoadFile("static/style/trackster.css")}),define(["libs/underscore","viz/trackster/tracks","viz/visualization","mvc/ui/icon-button","utils/query-string-parsing","mvc/grid/grid-view"],function(a,b,c,d,e,f){var g=function(){this.initialize&&this.initialize.apply(this,arguments)};g.extend=Backbone.Model.extend;var h=g.extend({initialize:function(a){this.baseURL=a},save_viz:function(){Galaxy.modal.show({title:"Saving...",body:"progress"});var a=[];$(".bookmark").each(function(){a.push({position:$(this).children(".position").text(),annotation:$(this).children(".annotation").text()})});var b=view.overview_drawable?view.overview_drawable.config.get_value("name"):null,c={view:view.to_dict(),viewport:{chrom:view.chrom,start:view.low,end:view.high,overview:b},bookmarks:a};return $.ajax({url:Galaxy.root+"visualization/save",type:"POST",dataType:"json",data:{id:view.vis_id,title:view.config.get_value("name"),dbkey:view.dbkey,type:"trackster",vis_json:JSON.stringify(c)}}).success(function(a){Galaxy.modal.hide(),view.vis_id=a.vis_id,view.has_changes=!1,window.history.pushState({},"",a.url+window.location.hash)}).error(function(){Galaxy.modal.show({title:"Could Not Save",body:"Could not save visualization. Please try again later.",buttons:{Cancel:function(){Galaxy.modal.hide()}}})})},createButtonMenu:function(){var e=this,f=d.create_icon_buttons_menu([{icon_class:"plus-button",title:"Add tracks",on_click:function(){c.select_datasets(Galaxy.root+"visualization/list_current_history_datasets",Galaxy.root+"api/datasets",{"f-dbkey":view.dbkey},function(c){a.each(c,function(a){view.add_drawable(b.object_from_template(a,view,view))})})}},{icon_class:"block--plus",title:"Add group",on_click:function(){view.add_drawable(new b.DrawableGroup(view,view,{name:"New Group"}))}},{icon_class:"bookmarks",title:"Bookmarks",on_click:function(){force_right_panel("0px"==$("div#right").css("right")?"hide":"show")}},{icon_class:"globe",title:"Circster",on_click:function(){window.location=e.baseURL+"visualization/circster?id="+view.vis_id}},{icon_class:"disk--arrow",title:"Save",on_click:function(){e.save_viz()}},{icon_class:"cross-circle",title:"Close",on_click:function(){e.handle_unsaved_changes(view)}}],{tooltip_config:{placement:"bottom"}});return this.buttonMenu=f,f},add_bookmark:function(a,b,c){var d=$("#right .unified-panel-body"),e=$("<div/>").addClass("bookmark").appendTo(d),f=$("<div/>").addClass("position").appendTo(e),g=($("<a href=''/>").text(a).appendTo(f).click(function(){return view.go_to(a),!1}),$("<div/>").text(b).appendTo(e));if(c){{var h=$("<div/>").addClass("delete-icon-container").prependTo(e).click(function(){return e.slideUp("fast"),e.remove(),view.has_changes=!0,!1});$("<a href=''/>").addClass("icon-button delete").appendTo(h)}g.make_text_editable({num_rows:3,use_textarea:!0,help_text:"Edit bookmark note"}).addClass("annotation")}return view.has_changes=!0,e},create_visualization:function(c,d,e,f,g){var h=this,i=new b.TracksterView(a.extend(c,{header:!1}));return i.editor=!0,$.when(i.load_chroms_deferred).then(function(a){if(d){var c=d.chrom,j=d.start,k=d.end,l=d.overview;c&&void 0!==j&&k?i.change_chrom(c,j,k):i.change_chrom(a[0].chrom)}else i.change_chrom(a[0].chrom);if(e)for(var m=0;m<e.length;m++)i.add_drawable(b.object_from_template(e[m],i,i));for(var m=0;m<i.drawables.length;m++)if(i.drawables[m].config.get_value("name")===l){i.set_overview(i.drawables[m]);break}if(f)for(var n,m=0;m<f.length;m++)n=f[m],h.add_bookmark(n.position,n.annotation,g);i.has_changes=!1}),this.set_up_router({view:i}),i},set_up_router:function(a){new c.TrackBrowserRouter(a),Backbone.history.start()},init_keyboard_nav:function(a){$(document).keyup(function(b){if(!$(b.srcElement).is(":input"))switch(b.which){case 37:a.move_fraction(.25);break;case 38:{Math.round(a.viewport_container.height()/15)}a.viewport_container.scrollTop(a.viewport_container.scrollTop()-20);break;case 39:a.move_fraction(-.25);break;case 40:{Math.round(a.viewport_container.height()/15)}a.viewport_container.scrollTop(a.viewport_container.scrollTop()+20)}})},handle_unsaved_changes:function(a){if(a.has_changes){var b=this;Galaxy.modal.show({title:"Close visualization",body:"There are unsaved changes to your visualization which will be lost if you do not save them.",buttons:{Cancel:function(){Galaxy.modal.hide()},"Leave without Saving":function(){$(window).off("beforeunload"),window.location=Galaxy.root+"visualization"},Save:function(){$.when(b.save_viz()).then(function(){window.location=Galaxy.root+"visualization"})}}})}else window.location=Galaxy.root+"visualization"}}),i=Backbone.View.extend({initialize:function(){ui=new h(Galaxy.root),ui.createButtonMenu(),ui.buttonMenu.$el.attr("style","float: right"),$("#center .unified-panel-header-inner").append(ui.buttonMenu.$el),$("#right .unified-panel-title").append("Bookmarks"),$("#right .unified-panel-icons").append("<a id='add-bookmark-button' class='icon-button menu-button plus-button' href='javascript:void(0);' title='Add bookmark'></a>"),$("#right-border").click(function(){view.resize_window()}),force_right_panel("hide"),galaxy_config.app.id?this.view_existing():e.get("dataset_id")?this.choose_existing_or_new():this.view_new()},choose_existing_or_new:function(){var a=this,b=e.get("dbkey"),c={},d={dbkey:b,dataset_id:e.get("dataset_id"),hda_ldda:e.get("hda_ldda"),gene_region:e.get("gene_region")};b&&(c["f-dbkey"]=b),Galaxy.modal.show({title:"View Data in a New or Saved Visualization?",body:"<p><ul style='list-style: disc inside none'>You can add this dataset as:<li>a new track to one of your existing, saved Trackster sessions if they share the genome build: <b>"+(b||"Not available.")+"</b></li><li>or create a new session with this dataset as the only track</li></ul></p>",buttons:{Cancel:function(){window.location=Galaxy.root+"visualization/list"},"View in saved visualization":function(){a.view_in_saved(d)},"View in new visualization":function(){a.view_new()}}})},view_in_saved:function(a){var b=new f({url_base:Galaxy.root+"visualization/list_tracks",dict_format:!0,embedded:!0});Galaxy.modal.show({title:"Add Data to Saved Visualization",body:b.$el,buttons:{Cancel:function(){window.location=Galaxy.root+"visualization/list"},"Add to visualization":function(){$(parent.document).find("input[name=id]:checked").each(function(){a.id=$(this).val(),window.location=Galaxy.root+"visualization/trackster?"+$.param(a)})}}})},view_existing:function(){var a=galaxy_config.app.viz_config;view=ui.create_visualization({container:$("#center .unified-panel-body"),name:a.title,vis_id:a.vis_id,dbkey:a.dbkey},a.viewport,a.tracks,a.bookmarks,!0),this.init_editor()},view_new:function(){var b=this;$.ajax({url:Galaxy.root+"api/genomes?chrom_info=True",data:{},error:function(){alert("Couldn't create new browser.")},success:function(c){Galaxy.modal.show({title:"New Visualization",body:b.template_view_new(c),buttons:{Cancel:function(){window.location=Galaxy.root+"visualization/list"},Create:function(){b.create_browser($("#new-title").val(),$("#new-dbkey").val()),Galaxy.modal.hide()}}});var d=c.map(function(a){return a[1]});galaxy_config.app.default_dbkey&&a.contains(d,galaxy_config.app.default_dbkey)&&$("#new-dbkey").val(galaxy_config.app.default_dbkey),$("#new-title").focus(),$("select[name='dbkey']").select2(),$("#overlay").css("overflow","auto")}})},template_view_new:function(a){for(var b='<form id="new-browser-form" action="javascript:void(0);" method="post" onsubmit="return false;"><div class="form-row"><label for="new-title">Browser name:</label><div class="form-row-input"><input type="text" name="title" id="new-title" value="Unnamed"></input></div><div style="clear: both;"></div></div><div class="form-row"><label for="new-dbkey">Reference genome build (dbkey): </label><div class="form-row-input"><select name="dbkey" id="new-dbkey">',c=0;c<a.length;c++)b+='<option value="'+a[c][1]+'">'+a[c][0]+"</option>";return b+='</select></div><div style="clear: both;"></div></div><div class="form-row">Is the build not listed here? <a href="'+Galaxy.root+'user/dbkeys?use_panels=True">Add a Custom Build</a></div></form>'},create_browser:function(a,b){$(document).trigger("convert_to_values"),view=ui.create_visualization({container:$("#center .unified-panel-body"),name:a,dbkey:b},galaxy_config.app.gene_region),this.init_editor(),view.editor=!0},init_editor:function(){$("#center .unified-panel-title").text(view.config.get_value("name")+" ("+view.dbkey+")"),galaxy_config.app.add_dataset&&$.ajax({url:Galaxy.root+"api/datasets/"+galaxy_config.app.add_dataset,data:{hda_ldda:"hda",data_type:"track_config"},dataType:"json",success:function(a){view.add_drawable(b.object_from_template(a,view,view))}}),$("#add-bookmark-button").click(function(){var a=view.chrom+":"+view.low+"-"+view.high,b="Bookmark description";return ui.add_bookmark(a,b,!0)}),ui.init_keyboard_nav(view),$(window).on("beforeunload",function(){return view.has_changes?"There are unsaved changes to your visualization that will be lost if you leave this page.":void 0})}});return{TracksterUI:h,GalaxyApp:i}});
//# sourceMappingURL=../../maps/viz/trackster.js.map