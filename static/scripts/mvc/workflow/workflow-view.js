"use strict";define("mvc/workflow/workflow-globals",{}),define(["utils/utils","mvc/workflow/workflow-globals","mvc/workflow/workflow-manager","mvc/workflow/workflow-canvas","mvc/workflow/workflow-node","mvc/workflow/workflow-icons","mvc/workflow/workflow-forms","mvc/ui/ui-misc","utils/async-save-text","libs/toastr","ui/editable-text"],function(o,e,t,a,i,n,s,l,r,d){function c(o){var e=$("#galaxy_tools").contents();0===e.length&&(e=$(document),$(this).removeClass("search_active"),e.find(".toolTitle").removeClass("search_match"),e.find(".toolSectionBody").hide(),e.find(".toolTitle").show(),e.find(".toolPanelLabel").show(),e.find(".toolSectionWrapper").each(function(){"recently_used_wrapper"!==$(this).attr("id")?$(this).show():$(this).hasClass("user_pref_visible")&&$(this).show()}),e.find("#search-no-results").hide(),e.find("#search-spinner").hide(),o&&e.find("#tool-search-query").val("search tools"))}return add_node_icon=function(o,e){var t=n[e];if(t){var a=$('<i class="icon fa">&nbsp;</i>').addClass(t);o.before(a)}},Backbone.View.extend({initialize:function(t){function i(){$.jStorage.set("overview-off",!1),$("#overview-border").css("right","0px"),$("#close-viewport").css("background-position","0px 0px")}function n(){$.jStorage.set("overview-off",!0),$("#overview-border").css("right","20000px"),$("#close-viewport").css("background-position","12px 0px")}var s=e.app=this;this.options=t,this.urls=t&&t.urls||{};var l=function(e,t){if(show_message("Saving workflow","progress"),s.workflow.check_changes_in_active_form(),!s.workflow.has_changes)return hide_modal(),void(t&&t());s.workflow.rectify_workflow_outputs(),o.request({url:Galaxy.root+"api/workflows/"+s.options.id,type:"PUT",data:{workflow:s.workflow.to_simple()},success:function(o){var e=$("<div/>").text(o.message);if(o.errors){e.addClass("warningmark");var a=$("<ul/>");$.each(o.errors,function(o,e){$("<li/>").text(e).appendTo(a)}),e.append(a)}else e.addClass("donemark");s.workflow.name=o.name,s.workflow.has_changes=!1,s.workflow.stored=!0,s.showWorkflowParameters(),o.errors?window.show_modal("Saving workflow",e,{Ok:hide_modal}):(t&&t(),hide_modal())},error:function(o){window.show_modal("Saving workflow failed.",o.err_msg,{Ok:hide_modal})}})};$("#tool-search-query").click(function(){$(this).focus(),$(this).select()}).keyup(function(){if($(this).css("font-style","normal"),this.value.length<3)c(!1);else if(this.value!=this.lastValue){$(this).addClass("search_active");var o=this.value;this.timer&&clearTimeout(this.timer),$("#search-spinner").show(),this.timer=setTimeout(function(){$.get(s.urls.tool_search,{q:o},function(o){if($("#search-no-results").hide(),$(".toolSectionWrapper").hide(),$(".toolSectionWrapper").find(".toolTitle").hide(),0!=o.length){var e=$.map(o,function(o,e){return"link-"+o});$(e).each(function(o,e){$("[id='"+e+"']").parent().addClass("search_match"),$("[id='"+e+"']").parent().show().parent().parent().show().parent().show()}),$(".toolPanelLabel").each(function(){for(var o=$(this),e=o.next(),t=!0;0!==e.length&&e.hasClass("toolTitle");){if(e.is(":visible")){t=!1;break}e=e.next()}t&&o.hide()})}else $("#search-no-results").show();$("#search-spinner").hide()},"json")},400)}this.lastValue=this.value}),this.canvas_manager=e.canvas_manager=new a(this,$("#canvas-viewport"),$("#overview")),this.reset(),this.datatypes=JSON.parse($.ajax({url:Galaxy.root+"api/datatypes",async:!1}).responseText),this.datatypes_mapping=JSON.parse($.ajax({url:Galaxy.root+"api/datatypes/mapping",async:!1}).responseText),this.ext_to_type=this.datatypes_mapping.ext_to_class_name,this.type_to_type=this.datatypes_mapping.class_to_classes,this._workflowLoadAjax(s.options.id,{success:function(o){s.reset(),s.workflow.from_simple(o,!0),s.workflow.has_changes=!1,s.workflow.fit_canvas_to_nodes(),s.scroll_to_nodes(),s.canvas_manager.draw_overview(),upgrade_message="",_.each(o.steps,function(e,t){var a="";e.errors&&(a+="<li>"+e.errors+"</li>"),_.each(o.upgrade_messages[t],function(o){a+="<li>"+o+"</li>"}),a&&(upgrade_message+="<li>Step "+(parseInt(t,10)+1)+": "+s.workflow.nodes[t].name+"<ul>"+a+"</ul></li>")}),upgrade_message?window.show_modal("Issues loading this workflow","Please review the following issues, possibly resulting from tool upgrades or changes.<p><ul>"+upgrade_message+"</ul></p>",{Continue:hide_modal}):hide_modal(),s.showWorkflowParameters()},beforeSubmit:function(o){show_message("Loading workflow","progress")}}),window.make_popupmenu&&make_popupmenu($("#workflow-options-button"),{Save:l,"Save As":function(){var o=$('<form><label style="display:inline-block; width: 100%;">Save as name: </label><input type="text" id="workflow_rename" style="width: 80%;" autofocus/><br><label style="display:inline-block; width: 100%;">Annotation: </label><input type="text" id="wf_annotation" style="width: 80%;" /></form>');window.show_modal("Save As a New Workflow",o,{OK:function(){var o=$("#workflow_rename").val().length>0?$("#workflow_rename").val():"SavedAs_"+s.workflow.name,e=$("#wf_annotation").val().length>0?$("#wf_annotation").val():"";$.ajax({url:s.urls.workflow_save_as,type:"POST",data:{workflow_name:o,workflow_annotation:e,workflow_data:function(){return JSON.stringify(s.workflow.to_simple())}}}).done(function(o){window.onbeforeunload=void 0,window.location=Galaxy.root+"workflow/editor?id="+o,hide_modal()}).fail(function(){hide_modal(),alert("Saving this workflow failed. Please contact this site's administrator.")})},Cancel:hide_modal})},Run:function(){window.location=Galaxy.root+"workflow/run?id="+s.options.id},"Edit Attributes":function(){s.workflow.clear_active_node()},"Auto Re-layout":function(){s.workflow.layout(),s.workflow.fit_canvas_to_nodes(),s.scroll_to_nodes(),s.canvas_manager.draw_overview()},Close:function(){s.workflow.check_changes_in_active_form(),workflow&&s.workflow.has_changes?(do_close=function(){window.onbeforeunload=void 0,window.document.location=s.urls.workflow_index},window.show_modal("Close workflow editor","There are unsaved changes to your workflow which will be lost.",{Cancel:hide_modal,"Save Changes":function(){l(null,do_close)}},{"Don't Save":do_close})):window.document.location=s.urls.workflow_index}}),overview_size=$.jStorage.get("overview-size"),void 0!==overview_size&&$("#overview-border").css({width:overview_size,height:overview_size}),$.jStorage.get("overview-off")?n():i(),$("#overview-border").bind("dragend",function(o,e){var t=$(this).offsetParent(),a=t.offset(),i=Math.max(t.width()-(e.offsetX-a.left),t.height()-(e.offsetY-a.top));$.jStorage.set("overview-size",i+"px")}),$("#close-viewport").click(function(){"0px"===$("#overview-border").css("right")?n():i()}),window.onbeforeunload=function(){if(workflow&&s.workflow.has_changes)return"There are unsaved changes to your workflow which will be lost."},this.options.workflows.length>0&&$("#left").find(".toolMenu").append(this._buildToolPanelWorkflows()),$("div.toolSectionBody").hide(),$("div.toolSectionTitle > span").wrap("<a href='#'></a>");var d=null;$("div.toolSectionTitle").each(function(){var o=$(this).next("div.toolSectionBody");$(this).click(function(){o.is(":hidden")?(d&&d.slideUp("fast"),d=o,o.slideDown("fast")):(o.slideUp("fast"),d=null)})}),r("workflow-name","workflow-name",s.urls.rename_async,"new_name"),$("#workflow-tag").click(function(){return $(".tag-area").click(),!1}),r("workflow-annotation","workflow-annotation",s.urls.annotate_async,"new_annotation",25,!0,4)},_buildToolPanelWorkflows:function(){var o=this,e=$('<div class="toolSectionWrapper"><div class="toolSectionTitle"><a href="#"><span>Workflows</span></a></div><div class="toolSectionBody"><div class="toolSectionBg"/></div></div>');return _.each(this.options.workflows,function(t){if(t.id!==o.options.id){var a=new l.ButtonIcon({icon:"fa fa-copy",cls:"ui-button-icon-plain",tooltip:"Copy and insert individual steps",onclick:function(){t.step_count<2?o.copy_into_workflow(t.id,t.name):Galaxy.modal.show({title:"Warning",body:"This will copy "+t.step_count+" new steps into your workflow.",buttons:{Cancel:function(){Galaxy.modal.hide()},Copy:function(){Galaxy.modal.hide(),o.copy_into_workflow(t.id,t.name)}}})}}),i=$("<a/>").attr("href","#").html(t.name).on("click",function(){o.add_node_for_subworkflow(t.latest_id,t.name)});e.find(".toolSectionBg").append($("<div/>").addClass("toolTitle").append(i).append(a.$el))}}),e},copy_into_workflow:function(o){var e=this;this._workflowLoadAjax(o,{success:function(o){e.workflow.from_simple(o,!1),upgrade_message="",$.each(o.upgrade_messages,function(o,t){upgrade_message+="<li>Step "+(parseInt(o,10)+1)+": "+e.workflow.nodes[o].name+"<ul>",$.each(t,function(o,e){upgrade_message+="<li>"+e+"</li>"}),upgrade_message+="</ul></li>"}),upgrade_message?window.show_modal("Subworkflow embedded with changes","Problems were encountered loading this workflow (possibly a result of tool upgrades). Please review the following parameters and then save.<ul>"+upgrade_message+"</ul>",{Continue:hide_modal}):hide_modal()},beforeSubmit:function(o){show_message("Importing workflow","progress")}})},reset:function(){this.workflow&&this.workflow.remove_all(),this.workflow=e.workflow=new t(this,$("#canvas-container"))},scroll_to_nodes:function(){var o,e,t=$("#canvas-viewport"),a=$("#canvas-container");e=a.width()<t.width()?(t.width()-a.width())/2:0,o=a.height()<t.height()?(t.height()-a.height())/2:0,a.css({left:e,top:o})},_workflowLoadAjax:function(e,t){$.ajax(o.merge(t,{url:this.urls.load_workflow,data:{id:e,_:"true"},dataType:"json",cache:!1}))},_moduleInitAjax:function(e,t){var a=this;o.request({type:"POST",url:Galaxy.root+"api/workflows/build_module",data:t,success:function(o){e.init_field_data(o),e.update_field_data(o),a.workflow.activate_node(e)}})},add_node_for_tool:function(o,e){node=this.workflow.create_node("tool",e,o),this._moduleInitAjax(node,{type:"tool",tool_id:o,_:"true"})},add_node_for_subworkflow:function(o,e){node=this.workflow.create_node("subworkflow",e,o),this._moduleInitAjax(node,{type:"subworkflow",content_id:o,_:"true"})},add_node_for_module:function(o,e){node=this.workflow.create_node(o,e),this._moduleInitAjax(node,{type:o,_:"true"})},display_pja:function(o,e){var t=this;$("#pja_container").append(get_pja_form(o,e)),$("#pja_container>.toolForm:last>.toolFormTitle>.buttons").click(function(){action_to_rem=$(this).closest(".toolForm",".action_tag").children(".action_tag:first").text(),$(this).closest(".toolForm").remove(),delete t.workflow.active_node.post_job_actions[action_to_rem],t.workflow.active_form_has_changes=!0})},display_pja_list:function(){return pja_list},display_file_list:function(o){addlist="<select id='node_data_list' name='node_data_list'>";for(var e in o.output_terminals)addlist+="<option value='"+e+"'>"+e+"</option>";return addlist+="</select>",addlist},new_pja:function(o,e,t){if(void 0===t.post_job_actions&&(t.post_job_actions={}),void 0===t.post_job_actions[o+e]){var a={};return a.action_type=o,a.output_name=e,t.post_job_actions[o+e]=null,t.post_job_actions[o+e]=a,display_pja(a,t),this.workflow.active_form_has_changes=!0,!0}return!1},showWorkflowParameters:function(){var e=/\$\{.+?\}/g,t=[],a=$("#workflow-parameters-container"),i=$("#workflow-parameters-box"),n="",s=[];$.each(this.workflow.nodes,function(a,i){i.config_form&&i.config_form.inputs&&o.deepeach(i.config_form.inputs,function(o){if("string"==typeof o.value){var t=o.value.match(e);t&&(s=s.concat(t))}}),i.post_job_actions&&$.each(i.post_job_actions,function(o,t){t.action_arguments&&$.each(t.action_arguments,function(o,t){var a=t.match(e);a&&(s=s.concat(a))})}),s&&$.each(s,function(o,e){-1===$.inArray(e,t)&&t.push(e)})}),t&&0!==t.length?($.each(t,function(o,e){n+="<div>"+e.substring(2,e.length-1)+"</div>"}),a.html(n),i.show()):(a.html(n),i.hide())},showAttributes:function(){$(".right-content").hide(),$("#edit-attributes").show()},showForm:function(e,t,a){var i=this,l="right-content",r=l+"-"+t.id,d=$("#"+l);if(a&&(d.find("#"+r).remove(),$('<div id="'+r+'" class="'+l+'"/>').remove()),e&&0==d.find("#"+r).length){var c=$('<div id="'+r+'" class="'+l+'"/>'),w=null;e.node=t,e.workflow=this.workflow,e.datatypes=this.datatypes,e.icon=n[t.type],e.cls="ui-portlet-narrow",e.inputs.unshift({type:"text",name:"__annotation",label:"Annotation",fixed:!0,value:t.annotation,area:!0,help:"Add an annotation or notes to this step. Annotations are available when a workflow is viewed."}),e.inputs.unshift({type:"text",name:"__label",label:"Label",value:t.label,help:"Add a step label.",fixed:!0,onchange:function(o){var e=!1;for(var a in i.workflow.nodes){var n=i.workflow.nodes[a];if(n.label&&n.label==o&&n.id!=t.id){e=!0;break}}var s=w.form.data.match("__label");w.form.element_list[s].model.set("error_text",e&&"Duplicate label. Please fix this before saving the workflow."),w.form.trigger("change")}}),e.onchange=function(){o.request({type:"POST",url:Galaxy.root+"api/workflows/build_module",data:{id:t.id,type:t.type,content_id:t.content_id,inputs:w.form.data.create()},success:function(o){t.update_field_data(o)}})},w="tool"==t.type?new s.Tool(e):new s.Default(e),c.append(w.form.$el),d.append(c)}$("."+l).hide(),d.find("#"+r).show(),d.show(),d.scrollTop()},isSubType:function(o,e){return o=this.ext_to_type[o],e=this.ext_to_type[e],this.type_to_type[o]&&e in this.type_to_type[o]},prebuildNode:function(o,e,t){var a=this,n=$("<div class='toolForm toolFormInCanvas'/>"),s=$("<div class='toolFormTitle unselectable'><span class='nodeTitle'>"+e+"</div></div>");add_node_icon(s.find(".nodeTitle"),o),n.append(s),n.css("left",$(window).scrollLeft()+20),n.css("top",$(window).scrollTop()+20),n.append($("<div class='toolFormBody'></div>"));var l=new i(this,{element:n});l.type=o,l.content_id=t;var r="<div><img height='16' align='middle' src='"+Galaxy.root+"static/images/loading_small_white_bg.gif'/> loading tool info...</div>";n.find(".toolFormBody").append(r);var d=$("<div class='buttons' style='float: right;'></div>");d.append($("<div/>").addClass("fa-icon-button fa fa-times").click(function(o){l.destroy()})),n.appendTo("#canvas-container");var c=$("#canvas-container").position(),w=$("#canvas-container").parent(),f=n.width(),h=n.height();return n.css({left:-c.left+w.width()/2-f/2,top:-c.top+w.height()/2-h/2}),d.prependTo(n.find(".toolFormTitle")),f+=d.width()+10,n.css("width",f),n.bind("dragstart",function(){a.workflow.activate_node(l)}).bind("dragend",function(){a.workflow.node_changed(this),a.workflow.fit_canvas_to_nodes(),a.canvas_manager.draw_overview()}).bind("dragclickonly",function(){a.workflow.activate_node(l)}).bind("drag",function(o,e){var t=$(this).offsetParent().offset(),a=e.offsetX-t.left,i=e.offsetY-t.top;$(this).css({left:a,top:i}),$(this).find(".terminal").each(function(){this.terminal.redraw()})}),l}})});
//# sourceMappingURL=../../../maps/mvc/workflow/workflow-view.js.map
