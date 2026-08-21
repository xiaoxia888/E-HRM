pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: window
    required property var backend
    width: 1480
    height: 900
    minimumWidth: 900
    minimumHeight: 500
    visible: true
    title: "信息化人力工作台"
    color: "#edf2f7"
    font.family: Qt.platform.os === "windows" ? "Microsoft YaHei UI" : "PingFang SC"

    property int activeModule: 0

    onClosing: function(close) {
        if (window.backend.running || window.backend.erpUploading
                || window.backend.erpTaskExtractionRunning) {
            close.accepted = false
            runningCloseDialog.open()
        }
    }

    FileDialog {
        id: importDialog
        title: "导入人员 Excel"
        currentFolder: window.backend.downloadsFolderUrl
        nameFilters: ["Excel 工作簿 (*.xlsx *.xlsm)"]
        fileMode: FileDialog.OpenFile
        onAccepted: window.backend.importExcel(selectedFile)
    }

    FileDialog {
        id: templateDialog
        title: "保存 Excel 模板"
        currentFolder: window.backend.downloadsFolderUrl
        currentFile: window.backend.templateDefaultUrl
        defaultSuffix: "xlsx"
        nameFilters: ["Excel 工作簿 (*.xlsx)"]
        fileMode: FileDialog.SaveFile
        onAccepted: window.backend.saveTemplate(selectedFile)
    }

    FolderDialog {
        id: outputDialog
        title: "选择保存位置"
        currentFolder: window.backend.downloadsFolderUrl
        onAccepted: window.backend.setOutputFolder(selectedFolder)
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: window.width < 1180 ? 184 : 220
            Layout.fillHeight: true
            color: "#ffffff"
            border.color: "#d6dde7"

            Column {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 7

                Item {
                    width: parent.width
                    height: 82
                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 13
                        Rectangle {
                            width: 44
                            height: 44
                            radius: 9
                            color: "#1677ff"
                            Image {
                                anchors.centerIn: parent
                                width: 27
                                height: 27
                                source: "../assets/app.svg"
                            }
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "信息化人力"
                            color: "#1e2430"
                            font.pixelSize: 20
                            font.weight: Font.Bold
                        }
                    }
                }

                NavItem {
                    width: parent.width
                    text: "权益单获取"
                    iconSource: "../assets/document.svg"
                    selected: window.activeModule === 0
                    onClicked: window.activeModule = 0
                }
                NavItem {
                    width: parent.width
                    text: "上传至 ERP"
                    iconSource: "../assets/upload.svg"
                    selected: window.activeModule === 1
                    onClicked: window.activeModule = 1
                }
                NavItem {
                    width: parent.width
                    text: "任务记录"
                    iconSource: "../assets/history.svg"
                    selected: window.activeModule === 2
                    onClicked: window.activeModule = 2
                }

                Item { width: 1; height: Math.max(10, parent.height - 82 - 52 * 4 - 28) }

                NavItem {
                    width: parent.width
                    text: "系统设置"
                    iconSource: "../assets/settings.svg"
                    selected: window.activeModule === 3
                    onClicked: window.activeModule = 3
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: window.activeModule

            Item {
                id: rightsPage

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: window.height < 700 ? 82 : 105
                        color: "#f9fbfd"
                        border.color: "#d6dde7"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: window.width < 1100 ? 18 : 32
                            anchors.rightMargin: window.width < 1100 ? 16 : 28
                            Column {
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    text: "单位权益单获取"
                                    color: "#1d2433"
                                    font.pixelSize: 25
                                    font.weight: Font.Bold
                                }
                                Text {
                                    text: "从 Excel 或 ERP 获取人员信息，自动查询并下载单位权益单"
                                    color: "#6b7380"
                                    font.pixelSize: 14
                                }
                            }
                            AppButton {
                                text: window.width < 1160 ? "获取申请" : "获取申请信息"
                                primary: true
                                enabled: !window.backend.running
                                         && !window.backend.erpUploading
                                         && !window.backend.erpTaskExtractionRunning
                                onClicked: erpTaskQueryDialog.open()
                            }
                            AppButton {
                                text: "下载 Excel 模板"
                                iconSource: "../assets/download.svg"
                                onClicked: templateDialog.open()
                            }
                            AppButton {
                                text: "导入 Excel"
                                iconSource: "../assets/upload.svg"
                                outline: true
                                onClicked: importDialog.open()
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.margins: window.height < 700 ? 12 : 24
                        Layout.topMargin: window.height < 700 ? 10 : 20
                        spacing: 18

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 10
                            color: "#fbfcfe"
                            border.color: "#d3dbe6"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 20
                                spacing: 15

                                Row {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Image {
                                        width: 22
                                        height: 22
                                        source: "../assets/document.svg"
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: window.backend.fileSummary
                                        color: "#242a36"
                                        font.pixelSize: 16
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: window.backend.hasRecords
                                        text: window.backend.recordStatusLabel
                                        color: window.backend.recordIssueCount > 0
                                            ? "#c77800" : "#12a150"
                                        font.pixelSize: 15
                                        font.weight: Font.DemiBold
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 12
                                    MetricCard {
                                        Layout.fillWidth: true
                                        title: "人员"
                                        value: window.backend.peopleCount.toString()
                                        iconSource: "../assets/people.svg"
                                    }
                                    MetricCard {
                                        Layout.fillWidth: true
                                        title: "查询条件"
                                        value: window.backend.conditionCount + " 组"
                                        iconSource: "../assets/list.svg"
                                    }
                                    MetricCard {
                                        Layout.fillWidth: true
                                        title: "预计 PDF"
                                        value: window.backend.expectedPdfCount + " 份"
                                        iconSource: "../assets/document.svg"
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Math.max(66, warningText.implicitHeight + 24)
                                    radius: 7
                                    color: "#fff8e8"
                                    border.color: "#ffc866"
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 10
                                        Rectangle {
                                            Layout.preferredWidth: 19
                                            Layout.preferredHeight: 19
                                            radius: 10
                                            color: "transparent"
                                            border.color: "#b87503"
                                            Text {
                                                anchors.centerIn: parent
                                                text: "i"
                                                color: "#b87503"
                                                font.pixelSize: 12
                                                font.weight: Font.Bold
                                            }
                                        }
                                        Text {
                                            id: warningText
                                            Layout.fillWidth: true
                                            Layout.alignment: Qt.AlignVCenter
                                            text: window.backend.planMessage
                                            color: "#9a6200"
                                            font.pixelSize: 14
                                            wrapMode: Text.WordWrap
                                        }
                                        AppButton {
                                            visible: window.backend.recordDetailCount > 0
                                            text: window.backend.recordIssueCount > 0
                                                ? "查看问题 (" + window.backend.recordIssueCount + ")"
                                                : "查看提示"
                                            onClicked: recordIssuesDialog.openForRow(0)
                                        }
                                    }
                                }

                                Text {
                                    text: "数据预览"
                                    color: "#202632"
                                    font.pixelSize: 18
                                    font.weight: Font.Bold
                                }

                                Rectangle {
                                    id: tablePanel
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    radius: 7
                                    color: "#ffffff"
                                    border.color: "#cfd8e4"
                                    clip: true

                                    property var ratios: [0.045, 0.15, 0.13, 0.105, 0.085, 0.17, 0.075, 0.12, 0.12]
                                    property var headers: ["状态", "任务编号", "单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间"]

                                    Column {
                                        anchors.fill: parent

                                        Rectangle {
                                            width: parent.width
                                            height: 48
                                            color: "#edf2f7"
                                            Row {
                                                anchors.fill: parent
                                                Repeater {
                                                    model: tablePanel.headers
                                                    Rectangle {
                                                        id: headerCell
                                                        required property int index
                                                        required property string modelData
                                                        width: tablePanel.width * tablePanel.ratios[headerCell.index]
                                                        height: 48
                                                        color: "transparent"
                                                        border.color: "#dce3ec"
                                                        Text {
                                                            anchors.centerIn: parent
                                                            text: headerCell.modelData
                                                            color: "#566071"
                                                            font.pixelSize: 13
                                                            font.weight: Font.DemiBold
                                                        }
                                                    }
                                                }
                                            }
                                        }

                                        ListView {
                                            id: recordList
                                            width: parent.width
                                            height: parent.height - 48
                                            clip: true
                                            model: window.backend.records
                                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                            delegate: Rectangle {
                                                id: recordRow
                                                required property int index
                                                required property var modelData
                                                width: recordList.width
                                                height: 50
                                                color: modelData.rowStatus === "error" ? "#fff7f6"
                                                    : modelData.rowStatus === "warning" ? "#fffaf0"
                                                    : modelData.rowStatus === "info" ? "#f5f9ff"
                                                    : recordRow.index % 2 ? "#f6f8fb" : "#ffffff"
                                                border.color: modelData.rowStatus === "error" ? "#f2c5c1"
                                                    : modelData.rowStatus === "warning" ? "#efd9a5"
                                                    : "#e1e7ef"
                                                Row {
                                                    anchors.fill: parent
                                                    Item {
                                                        width: tablePanel.width * tablePanel.ratios[0]
                                                        height: 50

                                                        Rectangle {
                                                            id: statusIcon
                                                            anchors.centerIn: parent
                                                            width: 21
                                                            height: 21
                                                            radius: 11
                                                            color: "transparent"
                                                            border.width: 1.5
                                                            border.color: recordRow.modelData.rowStatus === "error" ? "#d92d20"
                                                                : recordRow.modelData.rowStatus === "warning" ? "#d98b00"
                                                                : recordRow.modelData.rowStatus === "info" ? "#1677ff"
                                                                : "#2e9b61"
                                                            Text {
                                                                anchors.centerIn: parent
                                                                text: recordRow.modelData.rowStatus === "error" ? "!"
                                                                    : recordRow.modelData.rowStatus === "success" ? "✓" : "i"
                                                                color: statusIcon.border.color
                                                                font.pixelSize: recordRow.modelData.rowStatus === "success" ? 12 : 13
                                                                font.weight: Font.Bold
                                                            }
                                                        }

                                                        MouseArea {
                                                            id: statusMouse
                                                            anchors.fill: parent
                                                            hoverEnabled: true
                                                            cursorShape: recordRow.modelData.rowIssueCount > 0
                                                                ? Qt.PointingHandCursor : Qt.ArrowCursor
                                                            onClicked: {
                                                                if (recordRow.modelData.rowIssueCount > 0)
                                                                    recordIssuesDialog.openForRow(recordRow.modelData.rowNumber)
                                                            }

                                                            ToolTip {
                                                                visible: statusMouse.containsMouse
                                                                delay: 280
                                                                timeout: 12000
                                                                y: statusMouse.height + 4
                                                                contentItem: Text {
                                                                    width: 330
                                                                    text: recordRow.modelData.rowStatusLabel + "\n"
                                                                        + recordRow.modelData.rowIssueTooltip
                                                                    color: "#f8fafc"
                                                                    font.pixelSize: 13
                                                                    lineHeight: 1.25
                                                                    wrapMode: Text.WordWrap
                                                                }
                                                                background: Rectangle {
                                                                    color: "#243247"
                                                                    radius: 7
                                                                    border.color: "#3d4c61"
                                                                }
                                                            }
                                                        }
                                                    }
                                                    Repeater {
                                                        model: [
                                                            recordRow.modelData.taskNumber, recordRow.modelData.unit,
                                                            recordRow.modelData.department,
                                                            recordRow.modelData.name, recordRow.modelData.identity,
                                                            recordRow.modelData.insurance,
                                                            recordRow.modelData.startMonth, recordRow.modelData.endMonth
                                                        ]
                                                        Item {
                                                            id: dataCell
                                                            required property int index
                                                            required property string modelData
                                                            width: tablePanel.width * tablePanel.ratios[dataCell.index + 1]
                                                            height: 50
                                                            SelectableElidedText {
                                                                anchors.fill: parent
                                                                anchors.leftMargin: 10
                                                                anchors.rightMargin: 8
                                                                horizontalAlignment: dataCell.index >= 5 ? Text.AlignHCenter : Text.AlignLeft
                                                                text: dataCell.modelData
                                                                textColor: "#303744"
                                                                pixelSize: 13
                                                                emphasized: dataCell.index === 0
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 7
                                    Text {
                                        text: window.backend.statusText
                                        color: "#687181"
                                        font.pixelSize: 13
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: window.backend.running ? 7 : 0
                                        visible: window.backend.running
                                        radius: 4
                                        color: "#e7edf4"
                                        Rectangle {
                                            height: parent.height
                                            width: parent.width * Math.min(1, window.backend.progressCurrent / Math.max(1, window.backend.progressTotal))
                                            radius: 4
                                            color: "#1677ff"
                                            Behavior on width { NumberAnimation { duration: 220 } }
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            id: exportPanel
                            Layout.preferredWidth: window.width < 1180 ? 310 : 360
                            Layout.minimumWidth: 285
                            Layout.fillHeight: true
                            radius: 10
                            color: "#fbfcfe"
                            border.color: "#d3dbe6"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: window.height < 700 ? 14 : 20
                                spacing: 10

                                Text {
                                    text: "导出设置"
                                    color: "#202632"
                                    font.pixelSize: 19
                                    font.weight: Font.Bold
                                }

                                ScrollView {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    contentWidth: availableWidth
                                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                                    ScrollBar.vertical.policy: ScrollBar.AsNeeded

                                    Column {
                                        width: exportPanel.width - (window.height < 700 ? 28 : 40)
                                        spacing: 12

                                        ModeCard {
                                            width: parent.width
                                            title: "相同查询条件合并"
                                            helper: "预计生成 " + window.backend.batchExpectedPdfCount + " 份 PDF"
                                            selected: window.backend.exportMode === "batch"
                                            onClicked: window.backend.setExportMode("batch")
                                        }
                                        ModeCard {
                                            width: parent.width
                                            title: "每人单独一份"
                                            helper: "预计生成 " + window.backend.peopleCount + " 份 PDF"
                                            selected: window.backend.exportMode === "individual"
                                            onClicked: window.backend.setExportMode("individual")
                                        }

                                        Rectangle {
                                            width: parent.width
                                            height: 116
                                            radius: 8
                                            color: "#f5f8fc"
                                            border.color: "#d7e0ea"
                                            Column {
                                                anchors.fill: parent
                                                anchors.margins: 15
                                                spacing: 11
                                                Text {
                                                    text: "高级设置"
                                                    color: "#29303d"
                                                    font.pixelSize: 15
                                                    font.weight: Font.DemiBold
                                                }
                                                RowLayout {
                                                    width: parent.width
                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: "单批最多人数"
                                                        color: "#303744"
                                                        font.pixelSize: 14
                                                    }
                                                    BatchSizeControl {
                                                        from: 1
                                                        to: 100
                                                        value: window.backend.batchSize
                                                        enabled: window.backend.exportMode === "batch"
                                                        onValueEdited: function(value) {
                                                            window.backend.setBatchSize(value)
                                                        }
                                                    }
                                                }
                                                Text {
                                                    text: "每份 PDF 最多包含 1–100 人"
                                                    color: "#8a93a2"
                                                    font.pixelSize: 12
                                                }
                                            }
                                        }

                                        Text {
                                            text: "保存位置"
                                            color: "#303744"
                                            font.pixelSize: 14
                                            font.weight: Font.Medium
                                        }
                                        RowLayout {
                                            width: parent.width
                                            Rectangle {
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 42
                                                radius: 7
                                                color: "#ffffff"
                                                border.color: "#cbd5e1"
                                                Text {
                                                    anchors.fill: parent
                                                    anchors.leftMargin: 12
                                                    anchors.rightMargin: 12
                                                    verticalAlignment: Text.AlignVCenter
                                                    text: window.backend.outputPath
                                                    color: "#394150"
                                                    font.pixelSize: 13
                                                    elide: Text.ElideMiddle
                                                }
                                            }
                                            AppButton {
                                                text: "更改"
                                                onClicked: outputDialog.open()
                                            }
                                        }

                                        Item {
                                            width: 1
                                            height: 4
                                        }
                                    }
                                }

                                SettingsToggle {
                                    Layout.fillWidth: true
                                    checked: window.backend.uploadToErp
                                    enabled: !window.backend.running
                                    text: "下载完成后自动上传至 ERP"
                                    description: "按任务编号匹配申请并静默上传 PDF"
                                    onToggled: function(value) {
                                        window.backend.setUploadToErp(value)
                                    }
                                }

                                AppButton {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 54
                                    text: !window.backend.running
                                        ? "获取权益单"
                                        : window.backend.stopping
                                            ? "正在安全停止…"
                                            : "停止任务"
                                    primary: !window.backend.running
                                    danger: window.backend.running
                                    enabled: !window.backend.stopping
                                        && (window.backend.running
                                            || (window.backend.hasRecords
                                                && window.backend.recordIssueCount === 0))
                                    onClicked: {
                                        if (window.backend.running)
                                            stopTaskDialog.open()
                                        else
                                            window.backend.prepareExecution()
                                    }
                                }
                            }
                        }
                    }
                }
            }

            ErpUploadPage {
                backend: appBackend
            }
            PlaceholderPage {
                title: "任务记录"
                subtitle: "统一查看权益单下载和 ERP 上传任务。"
                description: "后续将支持按人员、时间和状态筛选，并可仅重试失败项目。"
            }
            SystemSettingsPage {
                backend: appBackend
            }
        }
    }

    ErpTaskQueryDialog {
        id: erpTaskQueryDialog
        backend: appBackend
    }

    ErpTaskProgressDialog {
        id: erpTaskProgressDialog
        backend: appBackend
    }

    RecordIssuesDialog {
        id: recordIssuesDialog
        backend: appBackend
    }

    Dialog {
        id: confirmationDialog
        width: 600
        height: Math.min(690, confirmationColumn.implicitHeight + 48)
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        focus: true
        padding: 24
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            color: "#ffffff"
            radius: 11
            border.color: "#dfe3e8"
        }
        contentItem: Column {
            id: confirmationColumn
            spacing: 17
            Text {
                text: "确认执行"
                color: "#202632"
                font.pixelSize: 22
                font.weight: Font.Bold
            }
            Text {
                width: parent.width
                text: "共 <b><font color='#1677ff'>" + window.backend.peopleCount + "</font></b> 人，将按 "
                      + "<b><font color='#1677ff'>" + window.backend.conditionCount + "</font></b> 组查询条件生成 "
                      + "<b><font color='#1677ff'>" + window.backend.expectedPdfCount + "</font></b> 份 PDF"
                textFormat: Text.RichText
                color: "#303744"
                font.pixelSize: 17
            }
            Rectangle {
                width: parent.width
                height: Math.min(225, Math.max(58, window.backend.conditionSummaries.length * 52 + 12))
                radius: 7
                color: "#ffffff"
                border.color: "#dfe3e8"
                ListView {
                    anchors.fill: parent
                    anchors.margins: 6
                    clip: true
                    model: window.backend.conditionSummaries
                    delegate: Rectangle {
                        id: conditionRow
                        required property var modelData
                        width: ListView.view.width
                        height: 52
                        color: "transparent"
                        border.color: "#edf0f3"
                        Text {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 8
                            verticalAlignment: Text.AlignVCenter
                            text: conditionRow.modelData.taskNumber + " · " + conditionRow.modelData.insurance + " · "
                                  + conditionRow.modelData.startMonth + " 至 " + conditionRow.modelData.endMonth + " · "
                                  + conditionRow.modelData.peopleCount + " 人"
                                  + (conditionRow.modelData.pdfCount > 1 ? " · " + conditionRow.modelData.pdfCount + " 份 PDF" : "")
                            color: "#303744"
                            font.pixelSize: 14
                            elide: Text.ElideRight
                        }
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 68
                radius: 7
                color: "#f0f7ff"
                border.color: "#91caff"
                Text {
                    anchors.fill: parent
                    anchors.margins: 12
                    text: "执行后将打开浏览器，请完成登录和安全验证。\n程序会在当前浏览器中自动继续。"
                    color: "#245b9e"
                    font.pixelSize: 14
                    lineHeight: 1.35
                }
            }
            Text {
                text: "结果 Excel <b><font color='#1677ff'>1</font></b> 份 · PDF "
                      + "<b><font color='#1677ff'>" + window.backend.expectedPdfCount + "</font></b> 份"
                      + (window.backend.uploadToErp ? " · 完成后自动上传 ERP" : "")
                textFormat: Text.RichText
                color: "#303744"
                font.pixelSize: 16
            }
            Text {
                width: parent.width
                text: "保存至：" + window.backend.confirmationOutputPath
                color: "#717a89"
                font.pixelSize: 13
                wrapMode: Text.WrapAnywhere
            }
            Row {
                anchors.right: parent.right
                spacing: 10
                AppButton {
                    text: "返回修改"
                    onClicked: confirmationDialog.close()
                }
                AppButton {
                    text: "确认并开始"
                    primary: true
                    onClicked: {
                        confirmationDialog.close()
                        window.backend.executePrepared()
                    }
                }
            }
        }
    }

    Dialog {
        id: validationDialog
        property string summary: ""
        property string details: ""
        width: 580
        height: details.length > 0 ? 430 : 250
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        padding: 24
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#dfe3e8" }
        contentItem: ColumnLayout {
            spacing: 15
            Text {
                text: "Excel 数据校验失败"
                color: "#202632"
                font.pixelSize: 21
                font.weight: Font.Bold
            }
            Text {
                Layout.fillWidth: true
                text: validationDialog.summary
                color: "#303744"
                font.pixelSize: 15
                wrapMode: Text.WordWrap
            }
            Text {
                visible: validationDialog.details.length > 0
                text: "请修改以下内容后重新导入："
                color: "#737c8b"
                font.pixelSize: 13
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: validationDialog.details.length > 0
                radius: 7
                color: "#f7f8fa"
                border.color: "#dfe3e8"
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 12
                    TextArea {
                        text: validationDialog.details
                        readOnly: true
                        wrapMode: TextArea.Wrap
                        color: "#303744"
                        background: null
                    }
                }
            }
            Row {
                Layout.alignment: Qt.AlignRight
                AppButton { text: "我知道了"; primary: true; onClicked: validationDialog.close() }
            }
        }
    }

    Dialog {
        id: messageDialog
        property string heading: ""
        property string message: ""
        width: 520
        height: 260
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        padding: 24
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#dfe3e8" }
        contentItem: ColumnLayout {
            spacing: 16
            Text { text: messageDialog.heading; font.pixelSize: 21; font.weight: Font.Bold; color: "#202632" }
            Text { Layout.fillWidth: true; Layout.fillHeight: true; text: messageDialog.message; wrapMode: Text.WrapAnywhere; color: "#4d5665"; font.pixelSize: 14 }
            Row { Layout.alignment: Qt.AlignRight; AppButton { text: "确定"; primary: true; onClicked: messageDialog.close() } }
        }
    }

    Dialog {
        id: resultDialog
        property string heading: ""
        property string message: ""
        property string details: ""
        width: 600
        height: 340
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        padding: 24
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#dfe3e8" }
        contentItem: ColumnLayout {
            spacing: 15
            Text { text: resultDialog.heading; font.pixelSize: 21; font.weight: Font.Bold; color: "#202632" }
            Text { text: resultDialog.message; font.pixelSize: 16; color: "#303744" }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 7
                color: "#f7f8fa"
                border.color: "#e1e5eb"
                Text { anchors.fill: parent; anchors.margins: 13; text: resultDialog.details; wrapMode: Text.WrapAnywhere; color: "#626c7b"; font.pixelSize: 13 }
            }
            Row {
                Layout.alignment: Qt.AlignRight
                spacing: 10
                AppButton { text: "关闭"; onClicked: resultDialog.close() }
                AppButton { text: "打开结果文件夹"; primary: true; onClicked: window.backend.openFolder(window.backend.lastOutputPath) }
            }
        }
    }

    Dialog {
        id: stopTaskDialog
        width: 500
        height: 285
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        padding: 24
        closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#dfe3e8" }
        contentItem: ColumnLayout {
            spacing: 16
            Text {
                text: "确认停止当前任务？"
                color: "#202632"
                font.pixelSize: 21
                font.weight: Font.Bold
            }
            Text {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: "程序会在最近的安全节点停止。\n\n已下载的 PDF 会保留；尚未处理的人员将在结果 Excel 中标记为“用户提前停止任务”。"
                wrapMode: Text.WordWrap
                color: "#4d5665"
                font.pixelSize: 14
                lineHeight: 1.3
            }
            Row {
                Layout.alignment: Qt.AlignRight
                spacing: 10
                AppButton { text: "继续执行"; onClicked: stopTaskDialog.close() }
                AppButton {
                    text: "确认停止"
                    danger: true
                    onClicked: {
                        stopTaskDialog.close()
                        window.backend.requestStop()
                    }
                }
            }
        }
    }

    Dialog {
        id: runningCloseDialog
        width: 470
        height: 220
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        padding: 24
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#dfe3e8" }
        contentItem: ColumnLayout {
            spacing: 16
            Text { text: "任务正在执行"; font.pixelSize: 21; font.weight: Font.Bold; color: "#202632" }
            Text {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: "请等待当前任务完成，或先安全停止任务后再退出。"
                color: "#4d5665"
                font.pixelSize: 14
                wrapMode: Text.WordWrap
            }
            Row {
                Layout.alignment: Qt.AlignRight
                spacing: 10
                AppButton { text: "继续执行"; onClicked: runningCloseDialog.close() }
                AppButton {
                    text: "停止任务"
                    danger: true
                    enabled: window.backend.erpUploading
                             || window.backend.erpTaskExtractionRunning
                             || !window.backend.stopping
                    onClicked: {
                        runningCloseDialog.close()
                        if (window.backend.erpTaskExtractionRunning)
                            window.backend.requestErpTaskExtractionStop()
                        else if (window.backend.erpUploading)
                            window.backend.requestManualErpStop()
                        else
                            stopTaskDialog.open()
                    }
                }
            }
        }
    }

    Connections {
        target: window.backend
        function onValidationFailed(summary, details) {
            validationDialog.summary = summary
            validationDialog.details = details
            validationDialog.open()
        }
        function onNotification(title, message) {
            messageDialog.heading = title
            messageDialog.message = message
            messageDialog.open()
        }
        function onConfirmationReady() {
            confirmationDialog.open()
        }
        function onExecutionFinished(title, message, details) {
            resultDialog.heading = title
            resultDialog.message = message
            resultDialog.details = details
            resultDialog.open()
        }
        function onErpTaskExtractionStarted() {
            erpTaskQueryDialog.close()
            erpTaskProgressDialog.open()
        }
        function onErpTaskExtractionFinished(title, message) {
            erpTaskProgressDialog.close()
            messageDialog.heading = title
            messageDialog.message = message
            messageDialog.open()
        }
    }
}
