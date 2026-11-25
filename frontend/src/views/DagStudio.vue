<template>
  <div class="studio-page">
    <div class="page-head">
      <div>
        <el-button link type="primary" @click="$router.push('/dag')">← 返回编排列表</el-button>
        <h2>{{ isNew ? '新建编排' : (graphName || '编辑编排') }}</h2>
        <p>从左侧拖组件到画布，从节点右侧端口拉线到下一节点。在空白处按住拖动画布，滚轮缩放。</p>
      </div>
      <div class="head-actions">
        <el-button :loading="saving" @click="save">保存</el-button>
        <el-button type="primary" :loading="running" @click="run">运行</el-button>
      </div>
    </div>

    <div class="studio" :class="{ 'has-drawer': showBottomDrawer, 'has-drawer-lg': showLlmDrawer }">
      <aside class="palette">
        <div v-for="cat in categoryList" :key="cat.key" class="cat">
          <div class="cat-name">{{ cat.label }}</div>
          <div
            v-for="op in cat.ops"
            :key="op.type"
            class="comp"
            draggable="true"
            @dragstart="onDragStart(op, $event)"
          >
            <i :style="{ background: op.color }" />
            <div>
              <b>{{ op.label }}</b>
              <span>{{ op.desc }}</span>
            </div>
          </div>
        </div>
      </aside>

      <div class="stage-frame">
      <div class="stage" ref="stageRef" :class="{ panning }" @dragover.prevent @drop="onDrop" @wheel.prevent="onWheel" @mousedown="onStageMouseDown" @click="onStageClick">
        <div class="world" :style="worldBox">
          <div class="world-inner" :style="worldInner">
        <svg class="wires" :width="canvas.w" :height="canvas.h">
          <defs>
            <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L0,6 L8,3 z" fill="#94a3b8" />
            </marker>
          </defs>
          <path
            v-for="(e, i) in edges"
            :key="i"
            :d="edgePath(e)"
            fill="none"
            stroke="#94a3b8"
            stroke-width="2"
            marker-end="url(#arrow)"
          />
          <path v-if="draft" :d="draft" fill="none" stroke="#1d6fd8" stroke-width="2" stroke-dasharray="6 4" />
        </svg>
        <div
          v-for="n in nodes"
          :key="n.id"
          class="node"
          :class="{ on: selected === n.id }"
          :style="nodeStyle(n)"
          @mousedown.stop="startMove(n, $event)"
          @click.stop="selected = n.id"
        >
          <span class="port in" @mousedown.stop="startLink(n, 'in', $event)" @mouseup.stop="endLink(n)" />
          <div class="body">
            <i :style="{ background: colorOf(n.type) }" />
            <div>
              <b>{{ labelOf(n.type) }}</b>
              <em>{{ nodeCaption(n) }}</em>
            </div>
          </div>
          <span class="port out" @mousedown.stop="startLink(n, 'out', $event)" />
        </div>
          </div>
        </div>
      </div>
      <button type="button" class="zoom-badge" title="点击恢复 100%" @click="resetZoom">{{ zoomPct }}%</button>
      </div>

      <transition name="sheet">
        <aside v-if="showTrainDrawer" class="drawer" @click.stop @mousedown.stop>
          <div class="grabber" />
          <div class="drawer-head">
            <div>
              <strong>模型训练</strong>
              <p>已按上游数据集、清洗规则自动带入，字段与「模型训练」页一致，可再改。</p>
            </div>
            <div class="drawer-ops">
              <el-button size="small" type="danger" plain @click="removeNode">删除节点</el-button>
              <el-button size="small" @click="selected = ''">收起</el-button>
            </div>
          </div>
          <div class="drawer-body" v-if="trainCfg">
            <el-form class="train-form" label-width="108px">
              <el-row :gutter="16">
                <el-col :md="12">
                  <el-form-item label="任务名称"><el-input v-model="trainCfg.name" placeholder="任务名称" /></el-form-item>
                  <el-form-item label="数据源类型">
                    <el-radio-group v-model="trainCfg.target_type" @change="onTrainTypeChange">
                      <el-radio-button label="bundle">逻辑数据集</el-radio-button>
                      <el-radio-button label="dataset">原始表</el-radio-button>
                      <el-radio-button label="live">实时表</el-radio-button>
                      <el-radio-button label="binding">清洗快照</el-radio-button>
                    </el-radio-group>
                  </el-form-item>
                  <el-form-item label="数据源">
                    <el-select v-model="trainCfg.target_id" filterable style="width: 100%" :placeholder="trainSourcePlaceholder" @change="onTrainSource">
                      <el-option v-for="s in trainSources" :key="s.id" :label="trainSourceLabel(s)" :value="s.id" />
                    </el-select>
                    <p v-if="trainCfg.target_type === 'live'" class="hint">已按上游「数据源接入」匹配活表，运行时读当前库表。</p>
                  </el-form-item>
                  <el-form-item v-if="trainCfg.target_type !== 'binding'" label="清洗规则">
                    <el-select v-model="trainCfg.rule_id" clearable filterable style="width: 100%" @change="onPickRule">
                      <el-option v-for="r in rules" :key="r.id" :label="r.name" :value="r.id" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="目标列">
                    <el-select v-model="trainCfg.target_col" filterable allow-create style="width: 100%">
                      <el-option v-for="c in trainColumns" :key="c" :label="trainColLabel(c)" :value="c" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="特征列">
                    <div class="field-tags" v-if="trainCfg.feature_cols?.length">
                      <el-tag
                        v-for="c in trainCfg.feature_cols"
                        :key="c"
                        closable
                        type="info"
                        effect="plain"
                        @close="trainCfg.feature_cols = trainCfg.feature_cols.filter(x => x !== c)"
                      >{{ trainColLabel(c) }}</el-tag>
                    </div>
                    <el-select v-model="trainCfg.feature_cols" multiple filterable :collapse-tags="false" :max-collapse-tags="99" class="field-select" style="width: 100%">
                      <el-option v-for="c in trainColumns.filter(x => x !== trainCfg.target_col)" :key="c" :label="trainColLabel(c)" :value="c" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :md="12">
                  <el-form-item label="任务类型">
                    <el-radio-group v-model="trainCfg.task_type">
                      <el-radio-button label="regression" :disabled="!canTrainRegression">回归</el-radio-button>
                      <el-radio-button label="classification" :disabled="!canTrainClassification">分类</el-radio-button>
                    </el-radio-group>
                  </el-form-item>
                  <el-form-item label="算法">
                    <el-select v-model="trainCfg.model_type" style="width: 100%" @change="onTrainModel">
                      <el-option-group v-for="g in zooGroups" :key="g.family" :label="g.family">
                        <el-option v-for="m in g.items" :key="m.key" :label="`${m.name}${m.available ? '' : '（未安装）'}`" :value="m.key" :disabled="!m.available" />
                      </el-option-group>
                    </el-select>
                  </el-form-item>
                  <p class="tip">{{ currentTrainModel?.tips }}</p>
                  <el-form-item label="参数预设">
                    <el-radio-group v-model="trainCfg.preset" @change="applyTrainPreset">
                      <el-radio-button v-for="opt in PRESET_OPTIONS" :key="opt.value" :label="opt.value">{{ opt.label }}</el-radio-button>
                    </el-radio-group>
                  </el-form-item>
                  <el-form-item v-for="p in currentTrainModel?.params || []" :key="p.key" :label="p.label">
                    <el-select v-if="p.type === 'select'" v-model="trainCfg.params[p.key]" style="width: 100%" @change="onTrainParamEdit">
                      <el-option v-for="opt in p.options" :key="String(opt)" :label="String(opt)" :value="opt" />
                    </el-select>
                    <el-input v-else-if="p.type === 'string'" v-model="trainCfg.params[p.key]" @input="onTrainParamEdit" />
                    <el-input-number
                      v-else
                      :key="`${trainParamEpoch}-${p.key}`"
                      v-model="trainCfg.params[p.key]"
                      :min="p.min"
                      :max="p.max"
                      :step="p.step != null ? p.step : (p.type === 'float' ? 0.01 : 1)"
                      :precision="p.step && p.step < 0.01 ? 4 : undefined"
                      style="width: 100%"
                      @change="onTrainParamEdit"
                    />
                  </el-form-item>
                  <el-form-item label="抽样行数">
                    <el-input-number v-model="trainCfg.sample_rows" :min="0" :max="2000000" style="width: 100%" />
                    <span class="hint">0 表示全量。示例建议 30000~80000。</span>
                  </el-form-item>
                  <el-form-item label="验证集比例"><el-input-number v-model="trainCfg.test_size" :min="0.05" :max="0.4" :step="0.05" /></el-form-item>
                  <el-form-item label="log1p 目标"><el-switch v-model="trainCfg.log_target" :disabled="trainCfg.task_type === 'classification'" /></el-form-item>
                </el-col>
              </el-row>
            </el-form>
          </div>
        </aside>
      </transition>
      <transition name="sheet">
        <aside v-if="showPredictDrawer" class="drawer" @click.stop @mousedown.stop>
          <div class="grabber" />
          <div class="drawer-head">
            <div>
              <strong>手填特征值</strong>
              <p>按所选训练模型的特征列填写一条样本。类别列填原始值（如中文站点名），数值填业务原值；预测时会套用训练保存的编码器 / 标准化。未填的列按 0 处理。带「共用 / 上游预测」标签的列留空即可，运行时自动取上游节点的值。</p>
            </div>
            <div class="drawer-ops">
              <el-button size="small" @click="addFeatureRow">添加特征</el-button>
              <el-button size="small" @click="selected = ''">收起</el-button>
            </div>
          </div>
          <div class="drawer-body" v-if="selectedNode">
            <el-form class="predict-form" label-width="132px" size="small">
              <el-row :gutter="12">
                <el-col
                  v-for="(row, idx) in selectedNode.config.feature_rows || []"
                  :key="(row.col || '') + idx"
                  :md="8"
                >
                  <el-form-item :label="headerLabel(row.col || '') || row.col || '特征'">
                    <div class="feat-edit">
                      <el-input v-if="!row.col" v-model="row.col" placeholder="列名" />
                      <el-input v-model="row.value" :placeholder="row.col || '值'" />
                      <el-tag v-if="isSharedFilledCol(row.col)" size="small" type="success" effect="plain">{{ fillSourceOf(row.col) }}</el-tag>
                      <el-button link type="danger" @click="selectedNode.config.feature_rows.splice(idx, 1)">删</el-button>
                    </div>
                  </el-form-item>
                </el-col>
              </el-row>
            </el-form>
          </div>
        </aside>
      </transition>
      <transition name="sheet">
        <aside v-if="showSharedDrawer" class="drawer" @click.stop @mousedown.stop>
          <div class="grabber" />
          <div class="drawer-head">
            <div>
              <strong>共用特征值</strong>
              <p>在这里填一次共同字段，拉线到「模型预测」后，手填模式下会自动写入同名特征列。</p>
            </div>
            <div class="drawer-ops">
              <el-button size="small" @click="fillSharedFromDownstream">提取下游公共列</el-button>
              <el-button size="small" @click="addFeatureRow">添加特征</el-button>
              <el-button size="small" @click="selected = ''">收起</el-button>
            </div>
          </div>
          <div class="drawer-body" v-if="selectedNode">
            <el-form class="predict-form" label-width="132px" size="small">
              <el-row :gutter="12">
                <el-col
                  v-for="(row, idx) in selectedNode.config.feature_rows || []"
                  :key="'share-' + (row.col || '') + idx"
                  :md="8"
                >
                  <el-form-item :label="headerLabel(row.col || '') || row.col || '特征'">
                    <div class="feat-edit">
                      <el-input v-if="!row.col" v-model="row.col" placeholder="列名" @change="onSharedFeatureChange" />
                      <el-input v-model="row.value" :placeholder="row.col || '值'" @change="onSharedFeatureChange" />
                      <el-button link type="danger" @click="removeSharedRow(idx)">删</el-button>
                    </div>
                  </el-form-item>
                </el-col>
              </el-row>
            </el-form>
          </div>
        </aside>
      </transition>
      <transition name="sheet">
        <aside v-if="showBundleDrawer" class="drawer" @click.stop @mousedown.stop>
          <div class="grabber" />
          <div class="drawer-head">
            <div>
              <strong>逻辑数据集</strong>
              <p>选择要送入下游清洗或训练的逻辑数据集。宽表行数较多时，训练节点里可再抽样。</p>
            </div>
            <div class="drawer-ops">
              <el-button size="small" type="danger" plain @click="removeNode">删除节点</el-button>
              <el-button size="small" @click="selected = ''">收起</el-button>
            </div>
          </div>
          <div class="drawer-body" v-if="selectedNode">
            <el-form class="node-form" label-width="108px">
              <el-form-item label="逻辑数据集">
                <el-select v-model="selectedNode.config.bundle_id" filterable style="width: 100%" @change="onPickBundle">
                  <el-option
                    v-for="b in bundles"
                    :key="b.id"
                    :label="`${b.name}（${b.n_rows || 0} 行）`"
                    :value="b.id"
                  />
                </el-select>
              </el-form-item>
              <p v-if="pickedBundleHint" class="hint">{{ pickedBundleHint }}</p>
            </el-form>
          </div>
        </aside>
      </transition>
      <transition name="sheet">
        <aside v-if="showCleanDrawer" class="drawer" @click.stop @mousedown.stop>
          <div class="grabber" />
          <div class="drawer-head">
            <div>
              <strong>清洗规则</strong>
              <p>套用已有规则，或跳转到规则编辑器新增。上游数据集的字段会作为清洗输入。</p>
            </div>
            <div class="drawer-ops">
              <el-button size="small" type="primary" plain :disabled="!selectedNode?.config?.rule_id" @click="openCleanRule(false)">去配置</el-button>
              <el-button size="small" type="primary" @click="openCleanRule(true)">新增</el-button>
              <el-button size="small" type="danger" plain @click="removeNode">删除节点</el-button>
              <el-button size="small" @click="selected = ''">收起</el-button>
            </div>
          </div>
          <div class="drawer-body" v-if="selectedNode">
            <el-form class="node-form" label-width="108px">
              <el-form-item label="清洗规则">
                <el-select v-model="selectedNode.config.rule_id" filterable style="width: 100%" @change="onPickRule">
                  <el-option v-for="r in rules" :key="r.id" :label="r.name" :value="r.id" />
                </el-select>
              </el-form-item>
              <p v-if="selectedNode.config.rule_name" class="hint">当前规则：{{ selectedNode.config.rule_name }}</p>
            </el-form>
          </div>
        </aside>
      </transition>
      <transition name="sheet">
        <aside v-if="showMysqlDrawer" class="drawer" @click.stop @mousedown.stop>
          <div class="grabber" />
          <div class="drawer-head">
            <div>
              <strong>数据源接入</strong>
              <p>选择已配置的 MySQL 库表。每次运行读当前数据，不是上传时的快照。</p>
            </div>
            <div class="drawer-ops">
              <el-button size="small" type="primary" plain @click="$router.push('/datasource')">去配置数据源</el-button>
              <el-button size="small" type="danger" plain @click="removeNode">删除节点</el-button>
              <el-button size="small" @click="selected = ''">收起</el-button>
            </div>
          </div>
          <div class="drawer-body" v-if="selectedNode">
            <el-form class="node-form" label-width="108px">
              <el-row :gutter="16">
                <el-col :md="8">
                  <el-form-item label="数据源">
                    <el-select v-model="selectedNode.config.source_id" filterable style="width: 100%" @change="onMysqlSourceChange">
                      <el-option
                        v-for="s in mysqlPicker.sources"
                        :key="s.id"
                        :label="`${s.name}（${s.host}:${s.port}）`"
                        :value="s.id"
                      />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :md="8">
                  <el-form-item label="数据库">
                    <el-select
                      v-model="selectedNode.config.database"
                      filterable
                      style="width: 100%"
                      :loading="mysqlPicker.loadingDbs"
                      :disabled="!selectedNode.config.source_id"
                      @change="onMysqlDbChange"
                    >
                      <el-option v-for="d in mysqlPicker.dbs" :key="d.name" :label="d.name" :value="d.name" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :md="8">
                  <el-form-item label="数据表">
                    <el-select
                      v-model="selectedNode.config.table"
                      filterable
                      style="width: 100%"
                      :loading="mysqlPicker.loadingTables"
                      :disabled="!selectedNode.config.database"
                    >
                      <el-option
                        v-for="t in mysqlPicker.tables"
                        :key="`${t.database}.${t.table}`"
                        :label="`${t.table}（约 ${t.rows || 0} 行）`"
                        :value="t.table"
                      />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
              <p class="hint">{{ pickedMysqlHint || '新数据进来后重新跑流程即可。' }}</p>
            </el-form>
          </div>
        </aside>
      </transition>
      <transition name="sheet">
        <aside v-if="showLlmDrawer" class="drawer drawer-lg" @click.stop @mousedown.stop>
          <div class="grabber" />
          <div class="drawer-head">
            <div>
              <strong>{{ selectedNode?.type === 'llm.risk' ? 'LLM 风险预警报告' : 'LLM 模型洞察' }}</strong>
              <p>{{ selectedNode?.type === 'llm.risk'
                ? '对预测结果结合知识库生成风险预警；用户短问题召回知识库，系统提示词控制预警文风。'
                : '依据上游训练指标与特征重要性生成洞察报告，运行后自动写入「洞察报告」列表；用户短问题召回知识库，系统提示词控制文风。' }}</p>
            </div>
            <div class="drawer-ops">
              <el-button size="small" type="primary" plain @click="$router.push('/llm')">去配置提示词</el-button>
              <el-button size="small" type="danger" plain @click="removeNode">删除节点</el-button>
              <el-button size="small" @click="selected = ''">收起</el-button>
            </div>
          </div>
          <div class="drawer-body" v-if="selectedNode">
            <el-form class="node-form" label-width="108px">
              <el-row :gutter="20">
                <el-col :md="12">
                  <el-form-item label="LLM 模型">
                    <el-select
                      v-model="selectedNode.config.llm_config_id"
                      filterable
                      clearable
                      placeholder="不选则用平台默认模型"
                      style="width: 100%"
                    >
                      <el-option
                        v-for="m in llms"
                        :key="m.id"
                        :label="`${m.name}（${m.model_name}）`"
                        :value="m.id"
                      />
                    </el-select>
                    <p class="hint mini">留空则用「LLM / 提示词」里标记为默认的模型。</p>
                  </el-form-item>
                </el-col>
                <el-col :md="12">
                  <el-form-item label="启用 RAG">
                    <el-switch v-model="selectedNode.config.use_rag" />
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="20">
                <el-col :md="12">
                  <el-form-item label="用户短问题">
                    <el-select
                      v-model="selectedNode.config.question_prompt_id"
                      filterable
                      clearable
                      placeholder="选模板，或选「自定义」自己填"
                      style="width: 100%"
                      @change="onPickQuestionPrompt"
                    >
                      <el-option label="自定义（在下方填写）" :value="CUSTOM_PICK" />
                      <el-option label="留空（不额外提问）" :value="EMPTY_PICK" />
                      <el-option v-for="p in questionPrompts" :key="p.id" :label="p.name" :value="p.id" />
                    </el-select>
                  </el-form-item>
                  <el-form-item>
                    <el-input
                      v-model="selectedNode.config.question"
                      type="textarea"
                      :rows="8"
                      placeholder="可留空。填写时会作为补充要求，同时用于知识库召回。"
                    />
                    <p class="hint mini">留空或选中的模板被清空都不影响报告输出；召回为空也会照常生成。</p>
                  </el-form-item>
                </el-col>
                <el-col :md="12">
                  <el-form-item label="系统提示词">
                    <el-select
                      v-model="selectedNode.config.system_prompt_id"
                      filterable
                      clearable
                      placeholder="选模板，或选「自定义」自己填"
                      style="width: 100%"
                      @change="onPickSystemPrompt"
                    >
                      <el-option label="自定义（在下方填写）" :value="CUSTOM_PICK" />
                      <el-option label="平台默认文风" :value="EMPTY_PICK" />
                      <el-option v-for="p in systemPrompts" :key="p.id" :label="p.name" :value="p.id" />
                    </el-select>
                  </el-form-item>
                  <el-form-item>
                    <el-input
                      v-model="selectedNode.config.system_prompt"
                      type="textarea"
                      :rows="8"
                      placeholder="控制文风与章节；可用 {metrics} {importance} {predictions} {context} {question} 占位符，运行时自动填充。"
                    />
                    <p class="hint mini">整段可自行改写；没写数据占位符时，平台会自动把指标/特征/召回片段补在指令后面。</p>
                  </el-form-item>
                </el-col>
              </el-row>
              <p class="hint">
                {{ selectedNode.type === 'llm.risk'
                  ? '运行时会带上上游模型预测切片，短问题用于召回知识库；跑完自动写入「洞察报告」。'
                  : '运行时会自动带上上游训练任务的评估指标、特征重要性、参数与预测切片；跑完自动写入「洞察报告」。' }}
              </p>
            </el-form>
          </div>
        </aside>
      </transition>

      <aside class="inspector">
        <h3>编排信息</h3>
        <el-form label-position="top" size="small">
          <el-form-item label="名称">
            <el-input v-model="graphName" placeholder="编排名称" />
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="graphDesc" type="textarea" :rows="2" placeholder="用途说明" />
          </el-form-item>
          <el-form-item label="场景">
            <el-select
              v-model="scenario"
              filterable
              allow-create
              default-first-option
              placeholder="下拉选择，或输入新场景后回车"
              style="width: 100%"
            >
              <el-option v-for="s in scenarios" :key="s.code" :label="s.name" :value="s.code" />
            </el-select>
          </el-form-item>
          <el-form-item label="定时">
            <el-select v-model="scheduleKind" style="width: 100%">
              <el-option label="不定时" value="none" />
              <el-option label="每小时" value="hourly" />
              <el-option label="每 6 小时" value="every_6h" />
              <el-option label="每天 8:00" value="daily" />
            </el-select>
          </el-form-item>
          <el-form-item label="启用定时">
            <el-switch v-model="scheduleEnabled" />
          </el-form-item>
        </el-form>

        <h3>节点</h3>
        <p v-if="!selectedNode" class="muted">点击画布节点查看详情，或从左侧拖入组件。</p>
        <template v-else>
          <p><b>{{ labelOf(selectedNode.type) }}</b></p>
          <p class="muted">{{ descOf(selectedNode.type) }}</p>

          <el-form v-if="selectedNode.type === 'source.mysql'" label-position="top" size="small">
            <p class="muted">数据源库表已在底部弹出栏打开，运行时读当前表。</p>
          </el-form>

          <el-form v-else-if="selectedNode.type === 'asset.dataset'" label-position="top" size="small">
            <el-form-item label="数据表">
              <el-select v-model="selectedNode.config.dataset_id" filterable style="width: 100%" @change="onPickDataset">
                <el-option
                  v-for="d in datasets"
                  :key="d.id"
                  :label="`${d.name}（${d.n_rows || 0} 行）`"
                  :value="d.id"
                />
              </el-select>
            </el-form-item>
          </el-form>

          <el-form v-else-if="selectedNode.type === 'asset.bundle'" label-position="top" size="small">
            <p class="muted">逻辑数据集已在底部弹出栏打开，可选择要接入的宽表。</p>
          </el-form>

          <el-form v-else-if="selectedNode.type === 'clean.apply_rule'" label-position="top" size="small">
            <p class="muted">清洗规则已在底部弹出栏打开，可选择规则或跳转编辑。</p>
          </el-form>

          <el-form v-else-if="selectedNode.type === 'feat.shared'" label-position="top" size="small">
            <p class="muted">共同手填特征已在底部弹出栏打开。从右侧端口拉到模型预测节点后，仅在「手填特征值」时写入同名字段；预测节点里单独填写的值优先。</p>
          </el-form>

          <el-form v-else-if="selectedNode.type === 'model.train'" label-position="top" size="small">
            <p class="muted">完整训练参数已在底部面板打开，可配置数据源、特征、算法与超参。</p>
          </el-form>

          <el-form v-else-if="isPredictNode" label-position="top" size="small">
            <el-form-item label="已训练模型">
              <el-select v-model="selectedNode.config.job_id" filterable clearable style="width: 100%" @change="onPickPredictJob">
                <el-option
                  v-for="j in successJobs"
                  :key="j.id"
                  :label="`${j.name} · ${j.target_col || ''} #${j.id}`"
                  :value="j.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="输入方式">
              <el-radio-group v-model="selectedNode.config.input_mode" @change="onPredictModeChange">
                <el-radio-button label="upstream">上游数据</el-radio-button>
                <el-radio-button label="manual">手填特征值</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <p v-if="selectedNode.config.input_mode === 'upstream'" class="muted">
              从上游数据表 / 逻辑数据集 / 清洗规则取特征后批量预测。
            </p>
            <p v-else class="muted">
              手填特征列已在底部弹出栏打开。
              <template v-if="incomingSharedCount">
                已连接 {{ incomingSharedCount }} 个共用特征值，同名字段会自动填入。
              </template>
            </p>
            <el-form-item label="输出列">
              <el-input v-model="selectedNode.config.output_col" placeholder="默认用模型目标列" />
            </el-form-item>
          </el-form>

          <el-form v-else-if="isLlmNode" label-position="top" size="small">
            <p class="muted">提示词与 RAG 已在底部弹出栏打开，可并排编辑短问题和系统提示词。</p>
          </el-form>

          <el-button size="small" type="danger" plain @click="removeNode">删除节点</el-button>
        </template>

        <h3>最近运行</h3>
        <div v-if="!lastRun" class="muted">尚未执行。</div>
        <div v-else class="run">
          <el-tag :type="lastRun.status === 'success' ? 'success' : 'danger'" size="small">{{ lastRun.status }}</el-tag>
          <span>{{ lastRun.duration_sec }}s</span>
          <pre>{{ lastRun.log_text }}</pre>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getGraph, getZoo, graphComponents, listBindings, listBundles, listDatasets, listGraphRuns, listJobs, listLLM, listPrompts, listRules,
  listDataSources, listSourceDatabases, listSourceTables,
  previewBundle, previewDataset, saveGraph, runGraph
} from '@/api'
import { getScenarios } from '@/api/user'
import { useUserStore } from '@/stores/user'
import { unwrapList } from '@/utils/paging'
import { featureColsForTarget, generatedColumnsFromSteps, headerLabel } from '@/utils/fieldLabels'
import { PRESET_OPTIONS, inferParamPreset, presetParams, resolveParamPreset, fillParamDefaults, coerceTaskType, allowedTasks } from '@/utils/modelPresets'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const ops = ref([])
const categories = ref({})
const datasets = ref([])
const bundles = ref([])
const bindings = ref([])
const rules = ref([])
const zoo = ref([])
const jobs = ref([])
const prompts = ref([])
const llms = ref([])
const mysqlPicker = reactive({
  sources: [],
  dbs: [],
  tables: [],
  loadingDbs: false,
  loadingTables: false
})
const graphId = ref(null)
const graphName = ref('未命名编排')
const graphDesc = ref('')
const scenario = ref('ecommerce')
const scenarios = ref([])
const scheduleKind = ref('none')
const scheduleEnabled = ref(false)
const nodes = ref([])
const edges = ref([])
const selected = ref('')
const saving = ref(false)
const running = ref(false)
const lastRun = ref(null)
const canvas = { w: 1680, h: 860 }
const zoom = ref(1)
const stageRef = ref(null)
const panning = ref(false)
const didPan = ref(false)
const ZOOM_MIN = 0.4
const ZOOM_MAX = 2
const dragOp = ref(null)
const linking = reactive({ from: null, x: 0, y: 0, mx: 0, my: 0 })
const draft = ref('')

const NODE_W = 188
const NODE_H = 64
const isNew = computed(() => route.name === 'DagNew' || !route.params.id)
const zoomPct = computed(() => Math.round(zoom.value * 100))
const worldBox = computed(() => ({
  width: `${Math.round(canvas.w * zoom.value)}px`,
  height: `${Math.round(canvas.h * zoom.value)}px`
}))
const worldInner = computed(() => ({
  width: `${canvas.w}px`,
  height: `${canvas.h}px`,
  transform: `scale(${zoom.value})`,
  transformOrigin: '0 0'
}))

const categoryList = computed(() => {
  const order = ['source', 'clean', 'feature', 'forecast', 'model', 'strategy', 'monitor', 'llm']
  return order
    .filter(k => ops.value.some(o => o.category === k))
    .map(k => ({
      key: k,
      label: categories.value[k] || k,
      ops: ops.value.filter(o => o.category === k)
    }))
})

const selectedNode = computed(() => {
  const n = nodes.value.find(x => x.id === selected.value)
  if (n && !n.config) n.config = {}
  return n
})
const showTrainDrawer = computed(() => selectedNode.value?.type === 'model.train')
const showPredictDrawer = computed(() => isPredictNode.value && selectedNode.value?.config?.input_mode === 'manual')
const showSharedDrawer = computed(() => selectedNode.value?.type === 'feat.shared')
const showBundleDrawer = computed(() => selectedNode.value?.type === 'asset.bundle')
const showCleanDrawer = computed(() => selectedNode.value?.type === 'clean.apply_rule')
const showMysqlDrawer = computed(() => selectedNode.value?.type === 'source.mysql')
// 提示词下拉里的两个特殊选项：自定义 / 留空
const CUSTOM_PICK = '__custom__'
const EMPTY_PICK = '__empty__'
const showLlmDrawer = computed(() => {
  const t = selectedNode.value?.type
  return t === 'llm.report' || t === 'llm.risk'
})
const showBottomDrawer = computed(() => showTrainDrawer.value || showPredictDrawer.value || showSharedDrawer.value || showBundleDrawer.value || showCleanDrawer.value || showMysqlDrawer.value || showLlmDrawer.value)
const trainCfg = computed(() => {
  const n = selectedNode.value
  if (n?.type !== 'model.train') return null
  return ensureTrainConfig(n.config)
})
const trainParamEpoch = ref(0)
let applyingTrainPreset = false
const currentTrainModel = computed(() => zoo.value.find(m => m.key === trainCfg.value?.model_type))
const trainTasks = computed(() => allowedTasks(currentTrainModel.value))
const canTrainRegression = computed(() => trainTasks.value.includes('regression'))
const canTrainClassification = computed(() => trainTasks.value.includes('classification'))
const zooGroups = computed(() => {
  const order = []
  const map = {}
  for (const m of zoo.value) {
    const fam = m.family || '其他'
    if (!map[fam]) {
      map[fam] = []
      order.push(fam)
    }
    map[fam].push(m)
  }
  return order.map(family => ({ family, items: map[family] }))
})
const successJobs = computed(() => (jobs.value || []).filter(j => j.status === 'success'))
const isPredictNode = computed(() => {
  const t = selectedNode.value?.type
  return t === 'model.predict' || t === 'model.apply'
})
const incomingSharedNodes = computed(() => {
  const n = selectedNode.value
  if (!n || !isPredictNode.value) return []
  return (edges.value || [])
    .filter(e => e.to === n.id)
    .map(e => nodes.value.find(x => x.id === e.from))
    .filter(x => x?.type === 'feat.shared')
})
const incomingSharedCount = computed(() => incomingSharedNodes.value.length)
const incomingSharedMap = computed(() => {
  const map = {}
  for (const n of incomingSharedNodes.value) {
    Object.assign(map, sharedFeatureMap(n))
  }
  return map
})
// 直接前驱里的「模型预测」节点：它们在运行时会把 output_col 的预测值
// 发布给下游手填节点，效果等同于共用特征，这里同步提示用户。
const incomingPredictOutputs = computed(() => {
  const map = {}
  const me = selectedNode.value
  if (!me) return map
  for (const e of edges.value) {
    if (e.to !== me.id) continue
    const n = nodes.value.find(x => x.id === e.from)
    if (!n || !isPredictType(n.type)) continue
    const col = n.config?.output_col
    if (col) map[col] = n.id
  }
  return map
})
const incomingFillMap = computed(() => ({ ...incomingSharedMap.value, ...incomingPredictOutputs.value }))
const isLlmNode = computed(() => {
  const t = selectedNode.value?.type
  return t === 'llm.report' || t === 'llm.risk'
})
const pickedBundleHint = computed(() => {
  const id = selectedNode.value?.config?.bundle_id
  const b = bundles.value.find(x => x.id === id)
  if (!b) return ''
  const parts = [`已选「${b.name}」`, `${b.n_rows || 0} 行`]
  if (b.n_cols) parts.push(`${b.n_cols} 列`)
  return parts.join(' · ')
})
const pickedMysqlHint = computed(() => {
  const n = selectedNode.value
  if (!n?.config?.source_id) return ''
  const src = mysqlPicker.sources.find(s => s.id === n.config.source_id)
  const db = n.config.database
  const tb = n.config.table
  const row = mysqlPicker.tables.find(t => t.table === tb && (!db || t.database === db))
  const bits = [src?.name, db, tb].filter(Boolean)
  if (!bits.length) return ''
  const extra = row?.rows != null ? ` · 约 ${row.rows} 行` : ''
  return `已选 ${bits.join(' / ')}${extra}`
})
const questionPrompts = computed(() => (prompts.value || []).filter(p => (p.prompt_kind || '') === 'question'))
const systemPrompts = computed(() => (prompts.value || []).filter(p => (p.prompt_kind || 'system') === 'system'))
const trainSources = computed(() => {
  const t = trainCfg.value?.target_type
  if (t === 'dataset') return datasets.value.filter(d => !isLiveDataset(d))
  if (t === 'live') return datasets.value.filter(isLiveDataset)
  if (t === 'binding') return bindings.value
  return bundles.value
})
const trainSourcePlaceholder = computed(() => {
  if (trainCfg.value?.target_type === 'live') return '选择实时库表'
  return '请选择'
})
const trainColumns = ref([])
const trainBaseColumns = ref([])
const trainColumnLabels = ref({})
const opMap = computed(() => Object.fromEntries(ops.value.map(o => [o.type, o])))

function isLiveDataset(d) {
  return !!(d && (d.origin_type === 'mysql_live' || d.is_live))
}

function matchLiveDataset(cfg = {}) {
  const table = cfg.table || cfg.source_table
  const db = cfg.database || cfg.source_db
  const sid = Number(cfg.source_id) || null
  const name = cfg.dataset_name
  const lives = datasets.value.filter(isLiveDataset)
  return lives.find(d => sid && Number(d.source_id) === sid && (!table || d.source_table === table))
    || lives.find(d => db && table && d.source_db === db && d.source_table === table)
    || lives.find(d => name && d.name === name)
    || lives[0]
    || null
}

function trainSourceLabel(s) {
  if (trainCfg.value?.target_type === 'live') {
    const loc = [s.source_db, s.source_table].filter(Boolean).join('.')
    const rows = s.n_rows != null ? ` · ${s.n_rows}行` : ''
    return loc ? `${s.name} · ${loc}${rows}` : `${s.name}（${s.n_rows || 0} 行）`
  }
  return `${s.name} (${s.n_rows || 0}行)`
}

function trainColLabel(c) {
  return trainColumnLabels.value[c] || headerLabel(c)
}

function defaultModelKey() {
  return zoo.value.find(m => m.available && m.key === 'xgboost')?.key
    || zoo.value.find(m => m.available)?.key
    || 'random_forest'
}

function ensureTrainConfig(cfg, isNewNode = false) {
  if (!cfg) return cfg
  if (!cfg.task_type) cfg.task_type = 'regression'
  if (!cfg.model_type) cfg.model_type = defaultModelKey()
  if (!cfg.params) cfg.params = {}
  if (!Array.isArray(cfg.feature_cols)) cfg.feature_cols = []
  if (!cfg.target_type) cfg.target_type = 'bundle'
  if (cfg.test_size == null) cfg.test_size = 0.2
  if (cfg.sample_rows == null) cfg.sample_rows = isNewNode ? 40000 : 0
  if (cfg.preset === 'accurate') cfg.sample_rows = 0
  if (cfg.log_target == null) cfg.log_target = !!isNewNode
  const model = zoo.value.find(m => m.key === cfg.model_type)
  cfg.task_type = coerceTaskType(model, cfg.task_type)
  if (cfg.task_type === 'classification') cfg.log_target = false
  if (!Object.keys(cfg.params).length) {
    const name = cfg.preset && cfg.preset !== 'custom' ? cfg.preset : 'balanced'
    cfg.preset = name
    const p = presetParams(model, name)
    if (p) cfg.params = p
  } else if (model && (cfg.preset == null || cfg.preset === '')) {
    cfg.preset = resolveParamPreset(model, cfg.params, cfg.param_preset)
  }
  if (model) {
    const filled = fillParamDefaults(model, cfg.params)
    const changed = (model.params || []).some(p => cfg.params?.[p.key] !== filled[p.key])
    if (changed) cfg.params = filled
  }
  return cfg
}

function applyTrainPreset(name) {
  const cfg = trainCfg.value
  if (!cfg) return
  const n = typeof name === 'string' ? name : cfg.preset
  if (!n || n === 'custom') return
  applyingTrainPreset = true
  cfg.preset = n
  if (n === 'accurate') cfg.sample_rows = 0
  const p = presetParams(currentTrainModel.value, n)
  if (p) {
    cfg.params = { ...p }
    trainParamEpoch.value += 1
  }
  nextTick(() => { applyingTrainPreset = false })
}

function onTrainParamEdit() {
  const cfg = trainCfg.value
  if (!cfg || applyingTrainPreset) return
  cfg.preset = inferParamPreset(currentTrainModel.value, cfg.params)
}

function onTrainModel() {
  const cfg = trainCfg.value
  if (!cfg) return
  cfg.task_type = coerceTaskType(currentTrainModel.value, cfg.task_type)
  if (cfg.task_type === 'classification') cfg.log_target = false
  if (!cfg.preset || cfg.preset === 'custom') cfg.preset = 'balanced'
  applyTrainPreset(cfg.preset)
}

function onTrainTypeChange() {
  const cfg = trainCfg.value
  if (!cfg) return
  cfg.target_id = null
  cfg.binding_id = null
  cfg.feature_cols = []
  trainBaseColumns.value = []
  trainColumns.value = []
  trainColumnLabels.value = {}
  if (cfg.target_type === 'live' && selectedNode.value) {
    applyUpstreamToTrain(cfg, selectedNode.value.id)
    if (!cfg.target_id) {
      const ds = matchLiveDataset({})
      if (ds) cfg.target_id = ds.id
    }
  }
  if (cfg.target_id) loadTrainSchema(true)
}

async function loadTrainSchema(resetFeatures = false) {
  const cfg = trainCfg.value
  if (!cfg?.target_id) {
    trainBaseColumns.value = []
    trainColumns.value = []
    trainColumnLabels.value = {}
    return
  }
  if (cfg.target_type === 'binding') {
    const b = bindings.value.find(x => x.id === cfg.target_id)
    cfg.binding_id = cfg.target_id
    trainBaseColumns.value = (b?.schema || []).map(c => typeof c === 'string' ? c : c.name).filter(Boolean)
    trainColumns.value = [...trainBaseColumns.value]
    trainColumnLabels.value = Object.fromEntries((trainColumns.value || []).map(c => [c, headerLabel(c)]))
  } else {
    cfg.binding_id = null
    const api = cfg.target_type === 'bundle' ? previewBundle : previewDataset
    const res = await api(cfg.target_id)
    trainBaseColumns.value = res.data?.columns || []
    trainColumns.value = [...trainBaseColumns.value]
    trainColumnLabels.value = res.data?.column_labels || {}
  }
  const rule = rules.value.find(r => Number(r.id) === Number(cfg.rule_id))
  const generated = generatedColumnsFromSteps(rule?.steps || [])
  trainColumns.value = [...new Set([...trainBaseColumns.value, ...generated])]
  for (const col of generated) {
    if (col !== cfg.target_col && !cfg.feature_cols.includes(col)) cfg.feature_cols.push(col)
  }
  if (resetFeatures) {
    if (trainColumns.value.includes('price_da') && (!cfg.target_col || cfg.target_col === 'load_mw')) {
      /* keep existing target if already set to wind/solar/price */
    }
    if (!cfg.target_col || !trainColumns.value.includes(cfg.target_col)) {
      cfg.target_col = ['price_da', 'wind_mw', 'solar_mw', 'load_mw', 'renewable_mw', 'Sales']
        .find(c => trainColumns.value.includes(c)) || trainColumns.value[0]
    }
    cfg.feature_cols = featureColsForTarget(trainColumns.value, cfg.target_col)
  }
}

function onTrainSource() {
  loadTrainSchema(true)
}

function upstreamNodes(id) {
  const seen = new Set()
  const acc = []
  const stack = [id]
  while (stack.length) {
    const cur = stack.pop()
    if (seen.has(cur)) continue
    seen.add(cur)
    for (const e of edges.value) {
      if (e.to !== cur) continue
      const n = nodes.value.find(x => x.id === e.from)
      if (!n || seen.has(n.id)) continue
      acc.push(n)
      stack.push(n.id)
    }
  }
  return acc
}

function applyUpstreamToTrain(cfg, nodeId) {
  if (!cfg || !nodeId) return
  const ups = upstreamNodes(nodeId)
  const mysql = ups.find(n => n.type === 'source.mysql')
  const src = ups.find(n => n.type === 'asset.bundle' || n.type === 'asset.dataset')
  const rule = ups.find(n => n.type === 'clean.apply_rule')
  if (mysql) {
    const mc = mysql.config || {}
    const ds = matchLiveDataset(mc)
    cfg.target_type = 'live'
    cfg.source_id = mc.source_id
    cfg.database = mc.database || mc.source_db
    cfg.table = mc.table || mc.source_table
    if (ds) cfg.target_id = Number(ds.id)
    cfg.binding_id = null
  } else if (src?.type === 'asset.bundle' && src.config?.bundle_id) {
    cfg.target_type = 'bundle'
    cfg.target_id = src.config.bundle_id
    cfg.binding_id = null
  } else if (src?.type === 'asset.dataset' && src.config?.dataset_id) {
    const ds = datasets.value.find(d => Number(d.id) === Number(src.config.dataset_id))
    cfg.target_type = isLiveDataset(ds) ? 'live' : 'dataset'
    cfg.target_id = src.config.dataset_id
    cfg.binding_id = null
  } else if (cfg.target_type === 'dataset' || cfg.target_type === 'live') {
    const ds = datasets.value.find(d => Number(d.id) === Number(cfg.target_id))
    if (isLiveDataset(ds)) cfg.target_type = 'live'
  }
  if (rule?.config?.rule_id) {
    cfg.rule_id = rule.config.rule_id
    cfg.rule_name = rule.config.rule_name
  }
}

function fillTrainFieldsIfEmpty(cfg) {
  const cols = trainColumns.value || []
  if (!cfg || !cols.length) return
  if (!cfg.target_col || !cols.includes(cfg.target_col)) {
    cfg.target_col = cols.find(c => ['price_da', 'wind_mw', 'solar_mw', 'load_mw', 'renewable_mw', 'Sales'].includes(c)) || cols[0]
  }
  const allowed = featureColsForTarget(cols, cfg.target_col)
  const live = (cfg.feature_cols || []).filter(c => allowed.includes(c))
  cfg.feature_cols = live.length ? live : allowed
}

async function openTrainDrawer(n) {
  if (!n || n.type !== 'model.train') return
  ensureTrainConfig(n.config)
  applyUpstreamToTrain(n.config, n.id)
  await loadTrainSchema(false)
  fillTrainFieldsIfEmpty(n.config)
}
function labelOf(t) { return opMap.value[mapNodeType(t)]?.label || t }
function descOf(t) { return opMap.value[mapNodeType(t)]?.desc || '' }
function colorOf(t) { return opMap.value[mapNodeType(t)]?.color || '#64748b' }
function mapNodeType(t) {
  if (t === 'model.apply') return 'model.predict'
  return t
}
function nodeStyle(n) {
  return { left: n.x + 'px', top: n.y + 'px', width: NODE_W + 'px', height: NODE_H + 'px' }
}
function nodeCaption(n) {
  const c = n.config || {}
  if (n.type === 'source.mysql') {
    const db = c.database || c.source_db
    const tb = c.table || c.source_table
    return db && tb ? `${db}.${tb}` : '选择库表'
  }
  if (n.type === 'asset.dataset') {
    return datasets.value.find(d => d.id === c.dataset_id)?.name || c.dataset_name || n.id
  }
  if (n.type === 'asset.bundle') {
    return bundles.value.find(b => b.id === c.bundle_id)?.name || c.bundle_name || n.id
  }
  if (n.type === 'clean.apply_rule') {
    return rules.value.find(r => r.id === c.rule_id)?.name || c.rule_name || n.id
  }
  if (n.type === 'model.train') {
    return c.name || c.target_col || n.id
  }
  if (n.type === 'model.predict' || n.type === 'model.apply') {
    const mode = c.input_mode === 'manual' ? '手填特征' : '上游数据'
    return `${mode}→${c.output_col || c.job_name || n.id}`
  }
  if (n.type === 'feat.shared') {
    const filled = (c.feature_rows || []).filter(r => r?.col && r.value !== '' && r.value != null).length
    return filled ? `${filled} 个共同字段` : '配置共同手填字段'
  }
  if (n.type === 'llm.report') {
    return c.question ? String(c.question).slice(0, 18) : '模型洞察'
  }
  if (n.type === 'llm.risk') {
    return c.question ? String(c.question).slice(0, 18) : '风险预警'
  }
  return n.id
}
function port(n, side) {
  const x = n.x + (side === 'out' ? NODE_W : 0)
  const y = n.y + NODE_H / 2
  return { x, y }
}
function bezier(a, b) {
  const dx = Math.max(40, (b.x - a.x) / 2)
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`
}
function edgePath(e) {
  const a = nodes.value.find(n => n.id === e.from)
  const b = nodes.value.find(n => n.id === e.to)
  if (!a || !b) return ''
  return bezier(port(a, 'out'), port(b, 'in'))
}

function clientToWorld(ev, stageEl) {
  const stage = stageEl || stageRef.value
  if (!stage) return { x: 0, y: 0 }
  const rect = stage.getBoundingClientRect()
  const z = zoom.value || 1
  return {
    x: (ev.clientX - rect.left + stage.scrollLeft) / z,
    y: (ev.clientY - rect.top + stage.scrollTop) / z
  }
}

function onWheel(ev) {
  const stage = stageRef.value
  if (!stage) return
  const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom.value * Math.exp(-ev.deltaY * 0.0018)))
  if (Math.abs(next - zoom.value) < 0.001) return
  const rect = stage.getBoundingClientRect()
  const wx = (ev.clientX - rect.left + stage.scrollLeft) / zoom.value
  const wy = (ev.clientY - rect.top + stage.scrollTop) / zoom.value
  zoom.value = next
  requestAnimationFrame(() => {
    stage.scrollLeft = wx * next - (ev.clientX - rect.left)
    stage.scrollTop = wy * next - (ev.clientY - rect.top)
  })
}

function resetZoom() {
  zoom.value = 1
}

function onStageMouseDown(ev) {
  if (ev.button !== 0) return
  if (linking.from) return
  if (ev.target?.closest?.('.node') || ev.target?.closest?.('.port') || ev.target?.closest?.('.zoom-badge')) return
  const stage = stageRef.value
  if (!stage) return
  panning.value = true
  didPan.value = false
  const sx = ev.clientX
  const sy = ev.clientY
  const sl = stage.scrollLeft
  const st = stage.scrollTop
  const move = (e) => {
    const dx = e.clientX - sx
    const dy = e.clientY - sy
    if (Math.hypot(dx, dy) > 3) didPan.value = true
    stage.scrollLeft = sl - dx
    stage.scrollTop = st - dy
  }
  const up = () => {
    panning.value = false
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
  ev.preventDefault()
}

function onStageClick() {
  if (didPan.value) {
    didPan.value = false
    return
  }
  selected.value = ''
}

function onDragStart(op, ev) {
  dragOp.value = op
  ev.dataTransfer.effectAllowed = 'copy'
}

function defaultNodeConfig(type) {
  if (type === 'model.train') return ensureTrainConfig({}, true)
  if (type === 'model.predict') {
    return { input_mode: 'upstream', job_id: null, output_col: '', feature_rows: [], override_rows: [] }
  }
  if (type === 'feat.shared') {
    return { feature_rows: defaultSharedRows() }
  }
  if (type === 'llm.report' || type === 'llm.risk') {
    return { question: '', system_prompt: '', use_rag: true, rag_top_k: 6 }
  }
  return {}
}

function onDrop(ev) {
  const op = dragOp.value
  if (!op) return
  const pt = clientToWorld(ev, ev.currentTarget)
  const id = 'n' + Date.now().toString(36)
  nodes.value.push({
    id,
    type: op.type,
    x: Math.max(8, pt.x - 80),
    y: Math.max(8, pt.y - 24),
    config: defaultNodeConfig(op.type)
  })
  selected.value = id
  dragOp.value = null
}

function startMove(n, ev) {
  selected.value = n.id
  const start = clientToWorld(ev)
  const ox = start.x - n.x
  const oy = start.y - n.y
  const move = (e) => {
    const pt = clientToWorld(e)
    n.x = Math.max(8, pt.x - ox)
    n.y = Math.max(8, pt.y - oy)
  }
  const up = () => {
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}

function startLink(n, side, ev) {
  if (side !== 'out') return
  const p = port(n, 'out')
  linking.from = n.id
  linking.x = p.x
  linking.y = p.y
  const move = (e) => {
    const pt = clientToWorld(e)
    linking.mx = pt.x
    linking.my = pt.y
    draft.value = bezier({ x: linking.x, y: linking.y }, { x: linking.mx, y: linking.my })
  }
  const up = () => {
    draft.value = ''
    linking.from = null
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
  ev.preventDefault()
}

function endLink(n) {
  const fromId = linking.from
  if (!fromId || fromId === n.id) return
  if (!edges.value.some(e => e.from === fromId && e.to === n.id)) {
    edges.value.push({ from: fromId, to: n.id })
  }
  linking.from = null
  draft.value = ''
  const from = nodes.value.find(x => x.id === fromId)
  if (from?.type === 'feat.shared' && isPredictType(n.type)) {
    applySharedToPredict(from, n, { emptyOnly: false })
    if ((n.config?.input_mode || '') !== 'manual') {
      ElMessage.info('已连接共用特征值。把该预测切到「手填特征值」后，同名字段会自动填入。')
    }
  }
  if (isPredictType(from?.type) && isPredictType(n.type)) {
    ElMessage.info(`已连接「${from.config?.output_col || '预测'}」。下游手填特征时，该列留空即自动取本节点的预测值。`)
  }
  if (n.type === 'model.train') openTrainDrawer(n)
}

function removeNode() {
  const id = selected.value
  nodes.value = nodes.value.filter(n => n.id !== id)
  edges.value = edges.value.filter(e => e.from !== id && e.to !== id)
  selected.value = ''
}

function onPickDataset(id) {
  const d = datasets.value.find(x => x.id === id)
  selectedNode.value.config.dataset_name = d?.name
}

async function loadMysqlSources() {
  const res = await listDataSources()
  mysqlPicker.sources = unwrapList(res)
}

async function loadMysqlDbs() {
  const n = selectedNode.value
  if (!n?.config?.source_id) {
    mysqlPicker.dbs = []
    mysqlPicker.tables = []
    return
  }
  mysqlPicker.loadingDbs = true
  try {
    const res = await listSourceDatabases(n.config.source_id)
    mysqlPicker.dbs = res.data?.items || []
    if (!n.config.database && res.data?.default) n.config.database = res.data.default
    if (n.config.database) await loadMysqlTables()
  } finally {
    mysqlPicker.loadingDbs = false
  }
}

async function loadMysqlTables() {
  const n = selectedNode.value
  if (!n?.config?.source_id || !n.config.database) {
    mysqlPicker.tables = []
    return
  }
  mysqlPicker.loadingTables = true
  try {
    const res = await listSourceTables(n.config.source_id, [n.config.database])
    mysqlPicker.tables = res.data?.items || []
  } finally {
    mysqlPicker.loadingTables = false
  }
}

async function onMysqlSourceChange() {
  const n = selectedNode.value
  if (!n) return
  n.config.database = ''
  n.config.table = ''
  mysqlPicker.tables = []
  await loadMysqlDbs()
}

async function onMysqlDbChange() {
  const n = selectedNode.value
  if (!n) return
  n.config.table = ''
  await loadMysqlTables()
}

function onPickBundle(id) {
  const b = bundles.value.find(x => x.id === id)
  selectedNode.value.config.bundle_name = b?.name
}

async function onPickRule(id) {
  const r = rules.value.find(x => x.id === id)
  if (selectedNode.value) selectedNode.value.config.rule_name = r?.name
  if (selectedNode.value?.type === 'model.train') await loadTrainSchema(false)
}

function fillPredictFeatureRows(n, job, force = false) {
  if (!n || !job) return
  const cols = job.feature_cols || []
  n.config.feature_cols = cols
  const existing = n.config.feature_rows || []
  const byCol = Object.fromEntries(existing.filter(r => r?.col).map(r => [r.col, r.value]))
  if (force || !existing.length) {
    n.config.feature_rows = cols.map(c => ({ col: c, value: byCol[c] ?? '' }))
  }
}

const DEFAULT_SHARED_COLS = [
  'year', 'month', 'day', 'hour', 'minute', 'second', 'weekday',
  'site', 'lat', 'lon',
  'temp_c', 'humidity', 'precip_mm',
  'wind_10m', 'wind_100m', 'wind_gust',
  'radiation', 'weather_code',
  'is_heat_wave', 'is_cold_wave', 'is_typhoon', 'is_convection'
]

function defaultSharedRows() {
  return DEFAULT_SHARED_COLS.map(col => ({ col, value: '' }))
}

function isPredictType(t) {
  return t === 'model.predict' || t === 'model.apply'
}

function sharedFeatureMap(n) {
  const map = {}
  for (const row of n?.config?.feature_rows || []) {
    if (row?.col && row.value !== '' && row.value != null) map[row.col] = row.value
  }
  return map
}

function isSharedFilledCol(col) {
  return !!col && Object.prototype.hasOwnProperty.call(incomingFillMap.value, col)
}

function fillSourceOf(col) {
  if (!col) return ''
  return Object.prototype.hasOwnProperty.call(incomingPredictOutputs.value, col) ? '上游预测' : '共用'
}

function applySharedToPredict(sharedNode, predictNode, { emptyOnly = true } = {}) {
  if (!sharedNode || !predictNode || !isPredictType(predictNode.type)) return
  if ((predictNode.config.input_mode || '') !== 'manual') return
  if (!predictNode.config) predictNode.config = {}
  const job = jobs.value.find(j => j.id === predictNode.config.job_id)
    || jobs.value.find(j => j.name === predictNode.config.job_name)
  if (job && !(predictNode.config.feature_rows || []).length) fillPredictFeatureRows(predictNode, job)
  if (!Array.isArray(predictNode.config.feature_rows)) predictNode.config.feature_rows = []
  const shared = sharedFeatureMap(sharedNode)
  const have = new Set(predictNode.config.feature_rows.map(r => r?.col).filter(Boolean))
  for (const col of Object.keys(shared)) {
    if (!have.has(col) && (job?.feature_cols || []).includes(col)) {
      predictNode.config.feature_rows.push({ col, value: '' })
      have.add(col)
    }
  }
  for (const row of predictNode.config.feature_rows) {
    if (!row?.col || !(row.col in shared)) continue
    if (!emptyOnly || row.value === '' || row.value == null) row.value = shared[row.col]
  }
}

function applyIncomingShared(predictNode, opts) {
  if (!predictNode) return
  for (const e of edges.value) {
    if (e.to !== predictNode.id) continue
    const src = nodes.value.find(x => x.id === e.from)
    if (src?.type === 'feat.shared') applySharedToPredict(src, predictNode, opts)
  }
}

function pushSharedToConnected(sharedNode) {
  if (!sharedNode) return
  for (const e of edges.value) {
    if (e.from !== sharedNode.id) continue
    const t = nodes.value.find(x => x.id === e.to)
    if (t) applySharedToPredict(sharedNode, t, { emptyOnly: false })
  }
}

function onSharedFeatureChange() {
  if (selectedNode.value?.type === 'feat.shared') pushSharedToConnected(selectedNode.value)
}

function removeSharedRow(idx) {
  const n = selectedNode.value
  if (!n?.config?.feature_rows) return
  n.config.feature_rows.splice(idx, 1)
  pushSharedToConnected(n)
}

function fillSharedFromDownstream() {
  const n = selectedNode.value
  if (n?.type !== 'feat.shared') return
  const downs = nodes.value.filter(p =>
    isPredictType(p.type) && edges.value.some(e => e.from === n.id && e.to === p.id)
  )
  const sets = downs.map(p => {
    const job = jobs.value.find(j => j.id === p.config?.job_id) || jobs.value.find(j => j.name === p.config?.job_name)
    const cols = job?.feature_cols?.length
      ? job.feature_cols
      : (p.config?.feature_rows || []).map(r => r.col).filter(Boolean)
    return new Set(cols)
  }).filter(s => s.size)
  if (!sets.length) {
    ElMessage.warning('请先把本组件拉线连到已选择模型的预测节点')
    return
  }
  let common = [...sets[0]]
  for (const s of sets.slice(1)) common = common.filter(c => s.has(c))
  if (!common.length) {
    ElMessage.warning('下游模型没有交集特征列')
    return
  }
  const byCol = sharedFeatureMap(n)
  n.config.feature_rows = common.map(c => ({ col: c, value: byCol[c] ?? '' }))
  pushSharedToConnected(n)
}

function onPredictModeChange(mode) {
  const n = selectedNode.value
  if (!n || !isPredictType(n.type)) return
  if (mode === 'manual') applyIncomingShared(n, { emptyOnly: false })
}

function onPickPredictJob(id) {
  const n = selectedNode.value
  if (!n) return
  const job = jobs.value.find(j => j.id === id)
  if (!job) return
  n.config.job_id = id
  n.config.job_name = job.name
  if (!n.config.output_col) n.config.output_col = job.target_col
  fillPredictFeatureRows(n, job, !n.config.feature_rows?.length)
  applyIncomingShared(n, { emptyOnly: true })
}

function addFeatureRow() {
  const n = selectedNode.value
  if (!n) return
  if (!Array.isArray(n.config.feature_rows)) n.config.feature_rows = []
  n.config.feature_rows.push({ col: '', value: '' })
}

function onPickQuestionPrompt(id) {
  const n = selectedNode.value
  if (!n) return
  n.config.question_prompt_id = id
  if (id === EMPTY_PICK) {
    n.config.question = ''
    return
  }
  // 选「自定义」时保留文本框内容，用户自己改写
  const p = prompts.value.find(x => x.id === id)
  if (p) n.config.question = p.content
}

function onPickSystemPrompt(id) {
  const n = selectedNode.value
  if (!n) return
  n.config.system_prompt_id = id
  if (id === EMPTY_PICK) {
    n.config.system_prompt = ''
    return
  }
  const p = prompts.value.find(x => x.id === id)
  if (p) n.config.system_prompt = p.content
}

function hasUpstreamData(nodeId) {
  return upstreamNodes(nodeId).some(n =>
    ['asset.dataset', 'asset.bundle', 'clean.apply_rule', 'source.file', 'source.mysql', 'asset.export_weather'].includes(n.type)
  )
}

function normalizeNode(n) {
  const type = n.type === 'model.apply' ? 'model.predict' : n.type
  const config = { ...(n.config || {}) }
  if (type === 'model.predict') {
    if (config.input_mode === 'model' || config.input_mode === 'hybrid' || !config.input_mode) {
      config.input_mode = 'upstream'
    }
    if (!Array.isArray(config.feature_rows)) config.feature_rows = []
    if (!Array.isArray(config.override_rows)) config.override_rows = []
  }
  if (type === 'feat.shared') {
    if (!Array.isArray(config.feature_rows) || !config.feature_rows.length) {
      config.feature_rows = defaultSharedRows()
    }
  }
  if (type === 'llm.report' || type === 'llm.risk') {
    if (config.use_rag == null) config.use_rag = true
    if (config.rag_top_k == null) config.rag_top_k = 6
    // 历史数据里可能存了对象/无效值，统一成合法的选中项
    for (const key of ['question_prompt_id', 'system_prompt_id']) {
      const v = config[key]
      if (v != null && typeof v !== 'number' && typeof v !== 'string') config[key] = null
    }
    const lid = Number(config.llm_config_id)
    config.llm_config_id = Number.isFinite(lid) && lid > 0 ? lid : null
  }
  return { ...n, type, config }
}

async function openCleanRule(create) {
  const nodeId = selected.value
  if (!create && !selectedNode.value?.config?.rule_id) {
    return ElMessage.warning('请先选择清洗规则')
  }
  await save()
  const dagId = graphId.value
  if (!dagId) return
  const query = { from: 'dag', dagId: String(dagId), nodeId: nodeId || '' }
  if (create) {
    router.push({ path: '/clean/rule/new', query })
  } else {
    router.push({ path: `/clean/rule/${selectedNode.value.config.rule_id}`, query })
  }
}

function applyGraph(row) {
  graphId.value = row.id
  graphName.value = row.name
  graphDesc.value = row.description || ''
  scenario.value = row.scenario_code || 'ecommerce'
  scheduleKind.value = row.schedule_kind || 'none'
  scheduleEnabled.value = !!row.schedule_enabled
  const g = row.graph || {}
  nodes.value = JSON.parse(JSON.stringify(g.nodes || [])).map(n => normalizeNode({ ...n, config: n.config || {} }))
  edges.value = JSON.parse(JSON.stringify(g.edges || []))
}

function resetBlank() {
  graphId.value = null
  graphName.value = '未命名编排'
  graphDesc.value = ''
  scenario.value = 'ecommerce'
  scheduleKind.value = 'none'
  scheduleEnabled.value = false
  nodes.value = []
  edges.value = []
  selected.value = ''
  lastRun.value = null
}

async function loadScenarios() {
  const res = await getScenarios()
  scenarios.value = res.data || []
  userStore.setScenarios(scenarios.value)
}

async function loadLastRun(id) {
  if (!id) {
    lastRun.value = null
    return
  }
  const res = await listGraphRuns({ graph_id: id })
  lastRun.value = unwrapList(res)[0] || null
}

function payload() {
  if (scheduleEnabled.value && scheduleKind.value === 'none') scheduleKind.value = 'daily'
  return {
    name: graphName.value,
    scenario_code: scenario.value,
    description: graphDesc.value,
    is_template: 0,
    schedule_kind: scheduleKind.value,
    schedule_enabled: scheduleEnabled.value,
    graph: { nodes: nodes.value, edges: edges.value }
  }
}

async function save() {
  saving.value = true
  try {
    const res = await saveGraph(payload(), graphId.value)
    applyGraph(res.data)
    await loadScenarios()
    ElMessage.success('编排已保存')
    if (isNew.value && res.data?.id) {
      await router.replace(`/dag/${res.data.id}`)
    }
    return res.data?.id
  } finally {
    saving.value = false
  }
}

async function run() {
  if (!graphId.value) await save()
  if (!graphId.value) return
  running.value = true
  ElMessage.success('编排已开始运行')
  try {
    const res = await runGraph(graphId.value)
    lastRun.value = res.data
    if (res.data?.status === 'success') {
      ElMessage.success('编排执行完成')
    } else if (res.data?.status === 'failed') {
      ElMessage.error(res.data?.error_message || '编排执行失败')
    } else {
      ElMessage.success('已返回运行结果')
    }
  } catch (err) {
    ElMessage.error(err?.message || '编排运行失败')
  } finally {
    running.value = false
  }
}

async function boot() {
  if (isNew.value) {
    resetBlank()
    return
  }
  const id = Number(route.params.id)
  if (!id) return
  const res = await getGraph(id)
  if (res.data) {
    applyGraph(res.data)
    await loadLastRun(id)
    await applyReturnFromClean()
  }
}

async function applyReturnFromClean() {
  const nodeId = route.query.node
  const ruleId = route.query.rule_id
  if (!nodeId && !ruleId) return
  if (ruleId) {
    const res = await listRules()
    rules.value = unwrapList(res)
    const n = nodes.value.find(x => x.id === nodeId)
    if (n) {
      if (!n.config) n.config = {}
      n.config.rule_id = Number(ruleId)
      onPickRule(n.config.rule_id)
    }
  }
  if (nodeId) selected.value = String(nodeId)
}

watch(() => [selectedNode.value?.type, selectedNode.value?.config?.source_id, selectedNode.value?.config?.database], () => {
  if (selectedNode.value?.type === 'source.mysql') loadMysqlDbs()
})

onMounted(async () => {
  const [c, d, b, r, z, bd, jb, pr, lm] = await Promise.all([
    graphComponents(),
    listDatasets(),
    listBundles(),
    listRules(),
    getZoo(),
    listBindings(),
    listJobs({ status: 'success' }),
    listPrompts(),
    listLLM({ page_size: 200 }),
    loadScenarios(),
    loadMysqlSources()
  ])
  ops.value = c.data?.ops || []
  categories.value = c.data?.categories || {}
  datasets.value = unwrapList(d)
  bundles.value = unwrapList(b)
  rules.value = unwrapList(r)
  zoo.value = z.data || []
  bindings.value = unwrapList(bd)
  jobs.value = unwrapList(jb)
  prompts.value = unwrapList(pr)
  llms.value = unwrapList(lm)
  await boot()
})

watch(() => route.params.id, () => boot())
watch(selected, async (id) => {
  const n = nodes.value.find(x => x.id === id)
  if (n?.type === 'model.predict' || n?.type === 'model.apply') {
    if (!n.config) n.config = {}
    if (!n.config.input_mode || ['model', 'hybrid'].includes(n.config.input_mode)) {
      n.config.input_mode = hasUpstreamData(n.id) ? 'upstream' : (n.config.feature_rows?.length ? 'manual' : 'upstream')
    }
    if (!Array.isArray(n.config.feature_rows)) n.config.feature_rows = []
    if (!Array.isArray(n.config.override_rows)) n.config.override_rows = []
    if (n.config.job_id && !n.config.feature_rows.length) {
      const job = jobs.value.find(j => j.id === n.config.job_id)
        || jobs.value.find(j => j.name === n.config.job_name)
      if (job) {
        n.config.job_id = job.id
        n.config.job_name = job.name
        if (!n.config.output_col) n.config.output_col = job.target_col
        fillPredictFeatureRows(n, job)
      }
    } else if (!n.config.job_id && n.config.job_name) {
      const job = jobs.value.find(j => j.name === n.config.job_name)
      if (job) {
        n.config.job_id = job.id
        if (!n.config.output_col) n.config.output_col = job.target_col
        if (!n.config.feature_rows.length) fillPredictFeatureRows(n, job)
      }
    }
    applyIncomingShared(n, { emptyOnly: true })
  }
  if (n?.type === 'feat.shared') {
    if (!n.config) n.config = {}
    if (!Array.isArray(n.config.feature_rows) || !n.config.feature_rows.length) {
      n.config.feature_rows = defaultSharedRows()
    }
  }
  if (n?.type === 'llm.report' || n?.type === 'llm.risk') {
    if (!n.config) n.config = {}
    if (n.config.use_rag == null) n.config.use_rag = true
    if (!n.config.question) n.config.question = ''
    if (!n.config.system_prompt) n.config.system_prompt = ''
  }
  if (n?.type !== 'model.train') return
  await openTrainDrawer(n)
})
</script>

<style scoped>
.head-actions { display: flex; gap: 8px; }
.studio-page {
  height: calc(100vh - 104px);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.studio {
  position: relative;
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr) 300px;
  gap: 12px;
  overflow: hidden;
}
.has-drawer .zoom-badge { bottom: calc(46% + 12px); }
.has-drawer-lg .zoom-badge { bottom: calc(58% + 12px); }
.palette, .inspector {
  min-height: 0;
  max-height: 100%;
  overflow-y: auto;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px;
  box-shadow: var(--shadow);
}
.stage-frame {
  position: relative;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}
.stage {
  position: relative;
  overflow: auto;
  background: #f7fafc;
  border: 1px solid var(--line);
  border-radius: 14px;
  height: 100%;
  min-height: 0;
  cursor: grab;
}
.cat { margin-bottom: 12px; }
.cat-name { font-size: 11px; letter-spacing: .08em; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; }
.comp {
  display: flex;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  margin-bottom: 6px;
  cursor: grab;
  background: var(--panel-soft);
}
.comp i, .body i {
  width: 8px;
  border-radius: 99px;
  flex: 0 0 8px;
}
.comp b, .body b { display: block; font-size: 13px; }
.comp span, .body em, .muted { color: var(--muted); font-size: 12px; font-style: normal; }
.override-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 6px;
  margin-bottom: 6px;
  align-items: center;
}
.feature-fill {
  max-height: 280px;
  overflow-y: auto;
  margin-bottom: 8px;
}
.feature-fill-row {
  display: grid;
  grid-template-columns: minmax(72px, 1fr) 1fr auto;
  gap: 6px;
  margin-bottom: 6px;
  align-items: center;
}
.feat-name {
  font-size: 12px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-actions .el-button { flex: 1; }
.stage.panning,
.stage.panning * { cursor: grabbing !important; }
.world { position: relative; }
.world-inner {
  position: relative;
  background:
    radial-gradient(circle at 1px 1px, #d5dee8 1px, transparent 0) 0 0 / 22px 22px,
    #f7fafc;
}
.zoom-badge {
  position: absolute;
  left: 12px;
  bottom: 12px;
  z-index: 8;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.92);
  color: var(--text);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--shadow);
}
.zoom-badge:hover { border-color: var(--accent); color: var(--accent); }
.wires { position: absolute; inset: 0; pointer-events: none; }
.node {
  position: absolute;
  display: flex;
  align-items: center;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow);
  cursor: grab;
  user-select: none;
}
.node.on { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.body { display: flex; gap: 8px; flex: 1; padding: 8px 6px; min-width: 0; }
.body em {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 140px;
}
.port {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #1d6fd8;
  margin: 0 6px;
}
.port.in { border-color: #0f766e; }
h3 { margin: 16px 0 8px; font-size: 14px; }
h3:first-child { margin-top: 0; }
.run { display: grid; gap: 8px; }
.run pre {
  white-space: pre-wrap;
  font-size: 12px;
  background: var(--panel-soft);
  padding: 10px;
  border-radius: 8px;
  max-height: 280px;
  overflow: auto;
}
.drawer {
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: 0;
  z-index: 9;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 16px 16px 12px 12px;
  box-shadow: 0 -12px 32px rgba(26, 36, 51, 0.14);
  max-height: 46%;
  min-height: 220px;
  display: flex;
  flex-direction: column;
}
.drawer-lg { max-height: 58%; min-height: 280px; }
.node-form :deep(.el-form-item) { margin-bottom: 12px; }
.grabber {
  width: 42px;
  height: 4px;
  border-radius: 99px;
  background: #d4dce6;
  margin: 8px auto 0;
}
.drawer-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px 8px;
  border-bottom: 1px solid var(--line);
}
.drawer-head p { color: var(--muted); font-size: 12px; margin-top: 2px; }
.drawer-ops { display: flex; gap: 6px; flex-wrap: wrap; align-items: flex-start; }
.drawer-body {
  flex: 1;
  min-height: 0;
  padding: 12px 16px 16px;
  overflow: auto;
}
.train-form :deep(.el-form-item) { margin-bottom: 10px; }
.train-form :deep(.el-radio-group) { flex-wrap: wrap; }
.predict-form :deep(.el-form-item) { margin-bottom: 10px; }
.feat-edit {
  display: flex;
  align-items: center;
  gap: 6px;
}
.feat-edit .el-input { flex: 1; }
.tip { color: var(--muted); font-size: 12px; margin: 0 0 8px 108px; }
.hint { color: var(--muted); font-size: 12px; }
.hint.mini { margin: 4px 0 0; font-size: 11px; line-height: 1.5; opacity: .85; }
.field-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.field-select :deep(.el-select__wrapper) {
  height: auto !important;
  min-height: 32px;
  align-items: flex-start;
}
.field-select :deep(.el-select__selection) {
  flex-wrap: wrap;
  height: auto;
}
.sheet-enter-active, .sheet-leave-active { transition: transform 0.22s ease, opacity 0.22s ease; }
.sheet-enter-from, .sheet-leave-to { transform: translateY(24px); opacity: 0; }
</style>
