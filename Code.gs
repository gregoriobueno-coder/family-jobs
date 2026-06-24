// Serverless Database Layer & API Gateway wrapper running on Google Apps Script
// Relational schema tables: Jobs, Profiles, Sources

function doGet(e) {
  try {
    var lock = LockService.getScriptLock();
    // Wait up to 30 seconds for a spreadsheet lock
    lock.waitLock(30000);
    
    var sheet = getOrCreateSheet("Jobs");
    var values = sheet.getDataRange().getValues();
    
    if (values.length <= 1) {
      return jsonResponse([]);
    }
    
    var headers = values[0];
    var jobs = [];
    for (var i = 1; i < values.length; i++) {
      var row = values[i];
      var job = {};
      var hasData = false;
      for (var j = 0; j < headers.length; j++) {
        var key = headers[j];
        if (key) {
          job[key] = row[j];
          if (row[j] !== "") hasData = true;
        }
      }
      if (hasData) {
        jobs.push(job);
      }
    }
    
    lock.releaseLock();
    return jsonResponse(jobs);
  } catch (err) {
    return jsonResponse({ error: err.message });
  }
}

function doPost(e) {
  try {
    var lock = LockService.getScriptLock();
    lock.waitLock(30000);
    
    var postData = e.postData ? e.postData.contents : e.parameter.data;
    if (!postData) {
      throw new Error("No data payload received.");
    }
    
    var payload = JSON.parse(postData);
    var action = payload.action;
    
    if (action === "getProfiles") {
      var profilesSheet = getOrCreateSheet("Profiles");
      var values = profilesSheet.getDataRange().getValues();
      var profiles = {};
      
      if (values.length > 1) {
        var headers = values[0];
        for (var i = 1; i < values.length; i++) {
          var row = values[i];
          var profile = {};
          var candidateName = "";
          for (var j = 0; j < headers.length; j++) {
            var key = headers[j];
            if (key === "candidate") {
              candidateName = row[j];
            } else if (key) {
              profile[key] = row[j];
            }
          }
          if (candidateName) {
            profiles[candidateName] = profile;
          }
        }
      } else {
        // Seed default empty profiles if sheet is new
        profiles = {
          "Greg": { lastName: "Bueno", address: "Orlando, FL", phone: "(555) 555-5555", email: "greg@email.com", summary: "Python engineer", experience: "Developer" },
          "Rachel": { lastName: "Bueno", address: "Orlando, FL", phone: "(555) 555-5555", email: "rachel@email.com", summary: "Corporate lead", experience: "Manager" },
          "Lorena": { lastName: "Gaitan Perez", address: "Orlando, FL", phone: "(555) 555-5555", email: "lorena@email.com", summary: "EdTech expert", experience: "Educator" }
        };
      }
      
      lock.releaseLock();
      return jsonResponse({ success: true, profiles: profiles });
    }
    
    if (action === "getSources") {
      var sourceSheet = getOrCreateSheet("Sources");
      var values = sourceSheet.getDataRange().getValues();
      var sources = [];
      if (values.length > 1) {
        var headers = values[0];
        for (var i = 1; i < values.length; i++) {
          var row = values[i];
          var source = {};
          for (var j = 0; j < headers.length; j++) {
            source[headers[j]] = row[j];
          }
          sources.push(source);
        }
      }
      lock.releaseLock();
      return jsonResponse({ success: true, sources: sources });
    }

    if (action === "addSource") {
      var sourceSheet = getOrCreateSheet("Sources");
      // Header: org | url | keywords | excludes | sector
      sourceSheet.appendRow([
        payload.org || "",
        payload.url || "",
        payload.keywords || "",
        payload.excludes || "",
        payload.sector || "All"
      ]);
      
      lock.releaseLock();
      return jsonResponse({ success: true });
    }
    
    if (action === "updateStatus") {
      var jobsSheet = getOrCreateSheet("Jobs");
      var values = jobsSheet.getDataRange().getValues();
      var headers = values[0];
      var idIndex = headers.indexOf("id");
      var statusIndex = headers.indexOf("userStatus");
      
      if (idIndex === -1 || statusIndex === -1) {
        throw new Error("Invalid sheet headers in Jobs.");
      }
      
      var updated = false;
      for (var i = 1; i < values.length; i++) {
        if (values[i][idIndex] == payload.jobId) {
          jobsSheet.getRange(i + 1, statusIndex + 1).setValue(payload.status);
          updated = true;
          break;
        }
      }
      
      lock.releaseLock();
      return jsonResponse({ success: updated, jobId: payload.jobId, newStatus: payload.status });
    }
    
    if (action === "batchUpsertJobs") {
      var jobsSheet = getOrCreateSheet("Jobs");
      var values = jobsSheet.getDataRange().getValues();
      var headers = values[0];
      
      // Map existing header indices
      var headerMap = {};
      var expectedHeaders = ["id", "title", "organization", "url", "location", "type", "source", "userStatus", "postDate", "compatibilityScore"];
      
      // Guarantee headers exist
      if (headers.length <= 1 && (headers[0] === "" || !headers[0])) {
        headers = expectedHeaders;
        jobsSheet.getRange(1, 1, 1, headers.length).setValues([headers]);
        values = [headers];
      }
      
      for (var h = 0; h < headers.length; h++) {
        headerMap[headers[h]] = h;
      }
      
      // Index existing rows by job ID
      var idCol = headerMap["id"];
      var rowMap = {};
      for (var r = 1; r < values.length; r++) {
        var existingId = values[r][idCol];
        if (existingId) {
          rowMap[existingId] = r; // Index of row in the values array
        }
      }
      
      var incomingJobs = payload.jobs || [];
      var updatedRowsCount = 0;
      var newRowsCount = 0;
      
      for (var k = 0; k < incomingJobs.length; k++) {
        var job = incomingJobs[k];
        var jobId = job.id;
        if (!jobId) continue;
        
        var rowData = new Array(headers.length).fill("");
        // Prepare row content matching current headers
        for (var key in job) {
          if (headerMap[key] !== undefined) {
            rowData[headerMap[key]] = job[key];
          }
        }
        
        if (rowMap[jobId] !== undefined) {
          // Update in-memory row
          var rowIndex = rowMap[jobId];
          // Preserve existing userStatus if not explicitly updated to prevent overwriting user triage status
          var existingStatusIndex = headerMap["userStatus"];
          if (existingStatusIndex !== undefined && !job.userStatus) {
            rowData[existingStatusIndex] = values[rowIndex][existingStatusIndex];
          }
          values[rowIndex] = rowData;
          updatedRowsCount++;
        } else {
          // Append in-memory row
          values.push(rowData);
          newRowsCount++;
        }
      }
      
      // Single atomic write back to Google Sheet range
      jobsSheet.getRange(1, 1, values.length, headers.length).setValues(values);
      
      lock.releaseLock();
      return jsonResponse({ success: true, updated: updatedRowsCount, appended: newRowsCount });
    }
    
    if (action === "generateResume") {
      // API Proxy to Gemini REST API to prevent client-side credential exposure
      var apiKey = PropertiesService.getScriptProperties().getProperty("GEMINI_API_KEY");
      if (!apiKey) {
        throw new Error("GEMINI_API_KEY Script Property is not configured in Google Apps Script settings.");
      }
      
      var url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=" + apiKey;
      var payloadBody = {
        contents: [
          {
            role: "user",
            parts: [{ text: payload.userQuery }]
          }
        ],
        systemInstruction: {
          parts: [{ text: payload.systemPrompt }]
        },
        generationConfig: {
          temperature: 0.2
        }
      };
      
      var options = {
        method: "post",
        contentType: "application/json",
        payload: JSON.stringify(payloadBody),
        muteHttpExceptions: true
      };
      
      var response = UrlFetchApp.fetch(url, options);
      var responseCode = response.getResponseCode();
      var responseText = response.getContentText();
      
      lock.releaseLock();
      
      if (responseCode !== 200) {
        return jsonResponse({ error: "Gemini API HTTP Error " + responseCode + ": " + responseText });
      }
      
      return HtmlService.createHtmlOutput(responseText)
        .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
        .setSandboxMode(HtmlService.SandboxMode.IFRAME)
        .setContent(responseText);
    }
    
    throw new Error("Unknown database API gateway action: " + action);
  } catch (err) {
    if (lock) lock.releaseLock();
    return jsonResponse({ error: err.message });
  }
}

// Utility functions
function getOrCreateSheet(name) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    // Write headers based on standard schemas
    if (name === "Jobs") {
      sheet.appendRow(["id", "title", "organization", "url", "location", "type", "source", "userStatus", "postDate", "compatibilityScore"]);
    } else if (name === "Profiles") {
      sheet.appendRow(["candidate", "lastName", "address", "phone", "email", "linkedIn", "authorized", "requiresSponsor", "targetSalary", "race", "veteranStatus", "disabilityStatus", "summary", "targetRoles", "coreCompetencies", "experience"]);
      // Add initial profile seeds
      sheet.appendRow(["Greg", "Bueno", "Orlando, FL", "(407) 555-1234", "greg.bueno@email.com", "linkedin.com/in/gregbueno", "Yes", "No", "120000", "White", "No", "No", "Senior Cloud Software Engineer specializing in Python microservices...", "Senior Python Developer, Backend Architect", "Python, AWS, React, serverless, SQL", "Senior Software Engineer at Tech Corp (2020-Present):\n- Orchestrated migration of legacy monolith to serverless backend using AWS Lambda, improving throughput by 45%.\n- Developed internal automated scraping utility using Python and requests, reducing credit usage by 90%.\n- Led team of 4 engineers to design secure web API interfaces."]);
      sheet.appendRow(["Rachel", "Bueno", "Orlando, FL", "(407) 555-5678", "rachel.bueno@email.com", "linkedin.com/in/rachelbueno", "Yes", "No", "95000", "Hispanic", "No", "No", "Operations Lead specializing in compliance administration...", "Operations Specialist, Business Analyst", "Operations management, regulatory compliance, client services", "Operations Manager at Logistics LLC (2021-Present):\n- Reduced operational overhead by 15% through workflow automation.\n- Coordinated audit compliance procedures across 3 distinct federal entities."]);
      sheet.appendRow(["Lorena", "Gaitan Perez", "Orlando, FL", "(407) 555-9012", "lorena.gp@email.com", "linkedin.com/in/lorenagp", "Yes", "No", "85000", "Hispanic", "No", "No", "Educational specialist with deep focus in curriculum development and EdTech integrations...", "Curriculum Coordinator, EdTech Specialist", "Instructional design, LMS setups, bilingual curriculum planning", "Senior Instructional Designer at Academics Academy (2019-Present):\n- Developed bilingual educational frameworks used by over 10,000 active students.\n- Integrated modern LMS tools, improving teacher administrative task speed by 30%."]);
    } else if (name === "Sources") {
      sheet.appendRow(["org", "url", "keywords", "excludes", "sector"]);
      // Seed default sources
      sheet.appendRow(["Figma", "https://boards.greenhouse.io/figma", "Software Engineer, Product Manager", "intern, co-op", "Greg"]);
      sheet.appendRow(["Vercel", "https://jobs.lever.co/vercel", "Developer, Engineer", "junior, associate", "Greg"]);
    }
  }
  return sheet;
}

function jsonResponse(data) {
  var output = ContentService.createTextOutput(JSON.stringify(data));
  output.setMimeType(ContentService.MimeType.JSON);
  return output;
}
